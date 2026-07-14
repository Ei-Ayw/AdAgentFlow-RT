"""里程碑一可靠性测试：执行租约、持久化重试、Worker 消息语义与 Repair 闭环。"""
from __future__ import annotations

import json
import asyncio
from contextlib import asynccontextmanager

import pytest


pytestmark = pytest.mark.asyncio


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def set(self, *, name, value, nx=False, ex=None):
        if nx and name in self.store:
            return None
        self.store[name] = value
        return True

    async def delete(self, key):
        return int(self.store.pop(key, None) is not None)

    async def exists(self, key):
        return int(key in self.store)

    async def eval(self, script, numkeys, key, owner):
        value = self.store.get(key)
        if value and json.loads(value).get("owner") == owner:
            del self.store[key]
            return 1
        return 0


async def test_execution_lock_only_owner_can_release(monkeypatch):
    from app.services import idempotency

    redis = FakeRedis()

    async def fake_get_redis():
        return redis

    monkeypatch.setattr(idempotency, "get_redis", fake_get_redis)
    owner = await idempotency.acquire_idempotent("task-1", "script_generation", ttl=30)
    assert owner
    assert not await idempotency.acquire_idempotent("task-1", "script_generation", ttl=30)
    assert not await idempotency.release_idempotent(
        "task-1", "script_generation", "another-owner"
    )
    assert await idempotency.is_idempotent_held("task-1", "script_generation")
    assert await idempotency.release_idempotent("task-1", "script_generation", owner)
    assert not await idempotency.is_idempotent_held("task-1", "script_generation")


class FakeExchange:
    def __init__(self):
        self.published = []

    async def publish(self, message, routing_key):
        self.published.append((message, routing_key))


class FakeChannel:
    def __init__(self):
        self.default_exchange = FakeExchange()
        self.declared = []

    async def declare_queue(self, name, durable, arguments):
        self.declared.append((name, durable, arguments))


class FakeConnection:
    is_closed = False


async def test_delayed_retry_is_persisted_in_rabbitmq_ttl_queue():
    from app.services.queue import EXCHANGE_NAME, QueueClient

    queue = QueueClient("amqp://unused")
    queue._connection = FakeConnection()
    queue._channel = FakeChannel()
    await queue.publish_step_delayed(
        "task-1", "script_generation", {"attempt": 2}, delay_seconds=5
    )

    name, durable, arguments = queue._channel.declared[0]
    assert name == "ad_task.script_generation.retry.5000.queue"
    assert durable is True
    assert arguments == {
        "x-message-ttl": 5000,
        "x-dead-letter-exchange": EXCHANGE_NAME,
        "x-dead-letter-routing-key": "ad_task.script_generation",
    }
    assert queue._channel.default_exchange.published[0][1] == name


class FakeProcess:
    def __init__(self, message, kwargs):
        self.message = message
        self.kwargs = kwargs

    async def __aenter__(self):
        return self.message

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type:
            self.message.failure_handled = (
                "reject" if self.message.redelivered else "requeue"
            )
        else:
            self.message.failure_handled = "ack"
        return False


class FakeMessage:
    def __init__(self, body, *, redelivered=False):
        self.body = body
        self.redelivered = redelivered
        self.process_kwargs = None
        self.failure_handled = None
        self.rejected = None

    def process(self, **kwargs):
        self.process_kwargs = kwargs
        return FakeProcess(self, kwargs)

    async def reject(self, *, requeue):
        self.rejected = requeue


class FailingOrchestrator:
    async def execute_step(self, task_id, step_id, payload):
        raise RuntimeError("database unavailable")


async def test_light_worker_requeues_first_infrastructure_failure():
    from app.workers.light_worker import LightWorker

    worker = object.__new__(LightWorker)
    worker.orchestrator = FailingOrchestrator()
    message = FakeMessage(
        json.dumps(
            {"task_id": "task-1", "step_id": "product_analysis", "payload": {}}
        ).encode()
    )

    await worker._handle_message(message, "ad_task.product_analysis")
    assert message.process_kwargs == {
        "requeue": True,
        "reject_on_redelivered": True,
    }
    assert message.failure_handled == "requeue"


async def test_light_worker_enforces_configured_execution_slots():
    from app.workers.light_worker import LightWorker

    class TrackingOrchestrator:
        def __init__(self):
            self.active = 0
            self.max_active = 0

        async def execute_step(self, task_id, step_id, payload):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1

    worker = object.__new__(LightWorker)
    worker.orchestrator = TrackingOrchestrator()
    worker._slots = asyncio.Semaphore(2)
    messages = [
        FakeMessage(
            json.dumps(
                {
                    "task_id": f"task-{index}",
                    "step_id": "product_analysis",
                    "payload": {"attempt": 1},
                }
            ).encode()
        )
        for index in range(6)
    ]

    await asyncio.gather(
        *(worker._run_limited(message, "ad_task.product_analysis") for message in messages)
    )

    assert worker.orchestrator.max_active == 2
    assert all(message.failure_handled == "ack" for message in messages)


class DummyQueue:
    def __init__(self):
        self.messages = []

    async def publish_step(self, task_id, step_id, payload):
        self.messages.append((task_id, step_id, payload))


async def test_repair_writes_target_and_invalidates_downstream(sqlite_db):
    from app.core.state_machine import StepStatus, TaskStatus, WORKFLOW_STEPS
    from app.db.database import session_scope
    from app.models.step import TaskStep
    from app.models.task import Task
    from app.services.orchestrator import WorkflowOrchestrator
    from app.services.tracing import Tracer

    task_id = "task-repair"
    with session_scope() as db:
        db.add(
            Task(
                task_id=task_id,
                trace_id="trace-repair",
                status=TaskStatus.RETRYING.value,
                input_payload={"product_name": "Fan"},
            )
        )
        for step_id in [*WORKFLOW_STEPS, "repair"]:
            status = StepStatus.SUCCESS.value
            if step_id == "script_generation":
                status = StepStatus.FAILED.value
            db.add(
                TaskStep(
                    task_id=task_id,
                    step_id=step_id,
                    step_name=step_id,
                    status=status,
                    output_payload={"old": step_id},
                )
            )

    orchestrator = object.__new__(WorkflowOrchestrator)
    orchestrator.queue = DummyQueue()
    repaired = {"hook": "new hook", "full_script": "new script", "cta": "buy"}
    await orchestrator._handle_repair_success(
        task_id,
        repaired,
        {
            "target_step": "script_generation",
            "trace_id": "trace-repair",
            "product": {"product_name": "Fan"},
            "history": {},
        },
        Tracer("trace-repair"),
    )

    with session_scope() as db:
        steps = {
            row.step_id: row
            for row in db.query(TaskStep).filter(TaskStep.task_id == task_id).all()
        }
        task = db.query(Task).filter(Task.task_id == task_id).first()

    assert steps["script_generation"].status == StepStatus.SUCCESS.value
    assert steps["script_generation"].output_payload == repaired
    for step_id in (
        "storyboard_planning",
        "material_suggestion",
        "quality_evaluation",
    ):
        assert steps[step_id].status == StepStatus.PENDING.value
        assert steps[step_id].output_payload is None
    assert task.status == TaskStatus.RUNNING.value
    assert orchestrator.queue.messages[0][1] == "storyboard_planning"
    assert (
        orchestrator.queue.messages[0][2]["history"]["script_generation"]
        == repaired
    )


async def test_orchestrator_rejects_illegal_terminal_state_transition(sqlite_db):
    from app.core.state_machine import StateMachineError, TaskStatus
    from app.db.database import session_scope
    from app.models.task import Task
    from app.services.orchestrator import WorkflowOrchestrator

    with session_scope() as db:
        db.add(
            Task(
                task_id="task-terminal",
                trace_id="trace-terminal",
                status=TaskStatus.SUCCESS.value,
            )
        )

    orchestrator = object.__new__(WorkflowOrchestrator)
    with pytest.raises(StateMachineError):
        orchestrator._transition_task("task-terminal", TaskStatus.RUNNING.value)


async def test_step_execution_keeps_each_run_and_result(sqlite_db):
    from app.agents.base import AgentResult
    from app.db.database import session_scope
    from app.models.execution import StepExecution
    from app.services.orchestrator import WorkflowOrchestrator

    orchestrator = object.__new__(WorkflowOrchestrator)
    first_id = orchestrator._start_execution(
        "task-history", "script_generation", {"attempt": 1, "input": "v1"}
    )
    orchestrator._finish_execution(
        first_id,
        AgentResult(
            success=True,
            output={"script": "v1"},
            model="mock-model",
            prompt_version="v2",
            input_tokens=10,
            output_tokens=20,
            latency_ms=30,
        ),
    )

    second_id = orchestrator._start_execution(
        "task-history", "script_generation", {"attempt": 2, "input": "v2"}
    )
    orchestrator._finish_execution_error(second_id, RuntimeError("worker crashed"))

    with session_scope() as db:
        executions = (
            db.query(StepExecution)
            .filter(StepExecution.task_id == "task-history")
            .order_by(StepExecution.run_number)
            .all()
        )

    assert [row.run_number for row in executions] == [1, 2]
    assert executions[0].status == "success"
    assert executions[0].output_payload == {"script": "v1"}
    assert executions[0].model_name == "mock-model"
    assert executions[0].input_tokens == 10
    assert executions[0].output_tokens == 20
    assert executions[1].status == "failed"
    assert executions[1].attempt == 2
    assert executions[1].error_message == "worker crashed"
