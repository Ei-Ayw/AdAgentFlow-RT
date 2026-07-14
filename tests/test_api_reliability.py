"""API 输入边界、请求幂等和健康探针测试。"""
from __future__ import annotations

import json
import importlib

import pytest
from pydantic import ValidationError


pytestmark = pytest.mark.asyncio


async def test_submit_request_rejects_blank_and_oversized_values():
    from app.api.task_router import SubmitTaskRequest

    with pytest.raises(ValidationError):
        SubmitTaskRequest(product_name="   ")
    with pytest.raises(ValidationError):
        SubmitTaskRequest(product_name="Fan", selling_points=["x" * 201])
    with pytest.raises(ValidationError):
        SubmitTaskRequest(
            product_name="Fan",
            selling_points=[f"point-{index}" for index in range(21)],
        )


async def test_idempotency_key_returns_existing_task(sqlite_db, monkeypatch):
    task_router = importlib.import_module("app.api.task_router")
    from app.api.task_router import SubmitTaskRequest, submit_task
    from app.models.task import Task

    calls = []

    class FakeOrchestrator:
        async def create_task(self, product, request_id=None):
            calls.append(request_id)
            db = sqlite_db["session_local"]()
            try:
                db.add(
                    Task(
                        task_id="task-idempotent",
                        trace_id="trace-idempotent",
                        request_id=request_id,
                        status="created",
                        input_payload=product,
                    )
                )
                db.commit()
            finally:
                db.close()
            return "task-idempotent"

    monkeypatch.setattr(task_router, "get_orchestrator", lambda: FakeOrchestrator())
    request = SubmitTaskRequest(product_name="Fan", selling_points=["cool"])
    db = sqlite_db["session_local"]()
    try:
        first = await submit_task(request, db, "request-key-123")
        second = await submit_task(request, db, "request-key-123")
    finally:
        db.close()

    assert first.task_id == second.task_id == "task-idempotent"
    assert calls == ["request-key-123"]


class HealthyConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement):
        return 1


class HealthyEngine:
    def connect(self):
        return HealthyConnection()


class HealthyRedis:
    async def ping(self):
        return True


class HealthyQueue:
    async def connect(self):
        return None


async def test_readiness_checks_all_dependencies(monkeypatch):
    from app import main
    from app.services import idempotency, queue

    async def get_healthy_redis():
        return HealthyRedis()

    monkeypatch.setattr(main, "engine", HealthyEngine())
    monkeypatch.setattr(idempotency, "get_redis", get_healthy_redis)
    monkeypatch.setattr(queue, "get_queue_client", lambda: HealthyQueue())

    response = await main.ready()
    assert response.status_code == 200
    assert json.loads(response.body) == {
        "status": "ready",
        "checks": {"postgres": "ok", "redis": "ok", "rabbitmq": "ok"},
    }


async def test_readiness_returns_503_when_dependency_fails(monkeypatch):
    from app import main
    from app.services import idempotency, queue

    async def broken_redis():
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(main, "engine", HealthyEngine())
    monkeypatch.setattr(idempotency, "get_redis", broken_redis)
    monkeypatch.setattr(queue, "get_queue_client", lambda: HealthyQueue())

    response = await main.ready()
    payload = json.loads(response.body)
    assert response.status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["checks"]["redis"] == "fail:ConnectionError"


async def test_metrics_exposes_prometheus_payload():
    from app import main

    response = main.metrics()
    assert response.status_code == 200
    assert b"adagentflow_outbox_publish_total" in response.body
    assert response.media_type.startswith("text/plain")


async def test_execution_history_api_returns_versioned_runs(sqlite_db):
    from app.api.task_router import list_step_executions
    from app.models.execution import StepExecution
    from app.models.task import Task

    db = sqlite_db["session_local"]()
    try:
        db.add(Task(task_id="task-api-history", trace_id="trace-history", status="running"))
        db.add_all(
            [
                StepExecution(
                    execution_id="execution-1",
                    task_id="task-api-history",
                    step_id="script_generation",
                    run_number=1,
                    attempt=1,
                    status="failed",
                    error_message="bad json",
                ),
                StepExecution(
                    execution_id="execution-2",
                    task_id="task-api-history",
                    step_id="script_generation",
                    run_number=2,
                    attempt=2,
                    status="success",
                    output_payload={"script": "ok"},
                ),
            ]
        )
        db.commit()

        rows = list_step_executions(
            "task-api-history", step_id="script_generation", limit=100, db=db
        )
    finally:
        db.close()

    assert [row.run_number for row in rows] == [2, 1]
    assert rows[0].output_payload == {"script": "ok"}
    assert rows[1].error_message == "bad json"
