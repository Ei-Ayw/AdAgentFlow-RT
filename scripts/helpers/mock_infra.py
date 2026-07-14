"""Mock 基础设施 - 在压测环境下替换真实的 RabbitMQ / Redis / PostgreSQL

设计原则：
1. **不依赖 docker** — 压测脚本应该随时能跑，不依赖任何外部服务。
2. **接口对等** — monkey-patch `app.services.queue` / `app.services.idempotency` / `app.db.database`，
   让真实的 orchestrator / agent 代码逻辑不被改动。
3. **可观测** — mock 同时收集事件，进入压测指标。
"""
from __future__ import annotations

import json
import random
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional


# ============================================================
# 1. Mock Redis - 内存版 KV
# ============================================================
class MockRedis:
    """进程内 Redis 替身，模拟 SETNX / EXPIRE / KEYS 等核心指令"""

    def __init__(self):
        self.store: Dict[str, str] = {}
        self.expires: Dict[str, float] = {}
        self.event_log: List[Dict[str, Any]] = []
        self.idempotent_acquires = 0
        self.idempotent_rejected = 0
        self.dedup_seen = 0
        self.dedup_dedup = 0

    def _is_expired(self, key: str) -> bool:
        if key not in self.expires:
            return False
        if time.time() > self.expires[key]:
            self.store.pop(key, None)
            self.expires.pop(key, None)
            return True
        return False

    async def set(self, name: str, value: str, nx: bool = False, ex: Optional[int] = None):
        self._is_expired(name)
        if nx and name in self.store:
            return None
        self.store[name] = value
        if ex is not None:
            self.expires[name] = time.time() + ex
        return True

    async def delete(self, *keys):
        n = 0
        for k in keys:
            if k in self.store:
                self.store.pop(k, None)
                self.expires.pop(k, None)
                n += 1
        return n

    async def exists(self, key: str) -> int:
        self._is_expired(key)
        return 1 if key in self.store else 0

    async def keys(self, pattern: str):
        if "*" not in pattern:
            return [k for k in self.store if k == pattern]
        if pattern.startswith("*") and pattern.count("*") == 1:
            suffix = pattern[1:]
            return [k for k in self.store if k.endswith(suffix)]
        if pattern.endswith("*") and pattern.count("*") == 1:
            prefix = pattern[:-1]
            return [k for k in self.store if k.startswith(prefix)]
        return list(self.store.keys())

    def count(self, prefix: str) -> int:
        return len([k for k in self.store if k.startswith(prefix)])


# ============================================================
# 2. Mock Database - 进程内 SQLAlchemy 替代
# ============================================================
class MockTask:
    def __init__(self, task_id, trace_id, status, product, max_retry=3):
        self.task_id = task_id
        self.trace_id = trace_id
        self.status = status
        self.product = product
        self.max_retry = max_retry
        self.retry_count = 0
        self.last_failure_reason = None
        self.created_at = time.time()
        self.finished_at = None
        self.output_payload: Dict[str, Any] = {}


class MockStep:
    def __init__(self, task_id, step_id, step_name):
        self.task_id = task_id
        self.step_id = step_id
        self.step_name = step_name
        self.status = "pending"
        self.retry_count = 0
        self.failure_reason = None
        self.error_message = None
        self.output_payload = None
        self.input_payload = None
        self.started_at = None
        self.finished_at = None
        self.latency_ms = 0
        self.token_cost = 0
        self.model_name = ""
        self.prompt_version = "v1.0"


class MockDeadLetter:
    def __init__(self, task_id, step_id, failure_reason, retry_count):
        self.task_id = task_id
        self.step_id = step_id
        self.failure_reason = failure_reason
        self.retry_count = retry_count
        self.created_at = time.time()


class MockEvaluation:
    def __init__(self, task_id, score, passed, risk_level, issues):
        self.task_id = task_id
        self.score = score
        self.passed = passed
        self.risk_level = risk_level
        self.issues = issues


class MockQuery:
    """Mock SQLAlchemy query — 支持链式 filter / first / all

    简化 filter 解析：只识别 `Model.field == value` 形式的条件。
    """

    def __init__(self, db, model):
        self.db = db
        self.model = model
        self.conditions: Dict[str, Any] = {}

    def filter(self, *args):
        for a in args:
            try:
                key = a.left.key
                val = a.right.value
                self.conditions[key] = val
            except AttributeError:
                pass
        return self

    def with_for_update(self):
        return self

    def first(self):
        items = self._apply()
        return items[0] if items else None

    def all(self):
        return self._apply()

    def count(self):
        return len(self._apply())

    def _apply(self):
        items = self.db._all_for_model(self.model)
        for key, val in self.conditions.items():
            items = [x for x in items if getattr(x, key, None) == val]
        return items


class MockSession:
    """Mock SQLAlchemy Session — 提供 add / commit / query / refresh"""

    def __init__(self, db):
        self.db = db
        self.pending = []

    def add(self, obj):
        self.pending.append(obj)
        # 同步到 ctx.db
        if isinstance(obj, MockTask):
            self.db.tasks[obj.task_id] = obj
        elif isinstance(obj, MockStep):
            if not self.db.get_step(obj.task_id, obj.step_id):
                self.db.steps.append(obj)
        elif isinstance(obj, MockDeadLetter):
            self.db.dead_letters.append(obj)
        elif isinstance(obj, MockEvaluation):
            self.db.evaluations.append(obj)

    def commit(self):
        pass

    def rollback(self):
        self.pending = []

    def refresh(self, obj):
        pass

    def query(self, model):
        return MockQuery(self.db, model)


class MockDB:
    def __init__(self):
        self.tasks: Dict[str, MockTask] = {}
        self.steps: List[MockStep] = []
        self.dead_letters: List[MockDeadLetter] = []
        self.evaluations: List[MockEvaluation] = []
        self.event_log: List[Dict[str, Any]] = []

    def _all_for_model(self, model):
        """根据 model 提取全部行（不含 filter）"""
        name = model.__name__
        if name == "Task":
            return list(self.tasks.values())
        if name == "TaskStep":
            return list(self.steps)
        if name == "DeadLetter":
            return list(self.dead_letters)
        if name == "EvaluationResult":
            return list(self.evaluations)
        return []

    def _first(self, model, filters):
        """根据 model 与 filter 提取第一条"""
        items = self._all(model, filters)
        return items[0] if items else None

    def _all(self, model, filters):
        """根据 model 与 filter 提取全部"""
        pool = self._all_for_model(model)
        # 简化：暂不解析 filter 表达式，依赖调用者先 add 再 query 的模式
        return pool

    def add_task(self, t):
        self.tasks[t.task_id] = t
        self.event_log.append({"type": "task.create", "task_id": t.task_id})

    def add_step(self, s):
        self.steps.append(s)

    def add_dead_letter(self, dl):
        self.dead_letters.append(dl)

    def get_step(self, task_id, step_id):
        for s in self.steps:
            if s.task_id == task_id and s.step_id == step_id:
                return s
        return None


# ============================================================
# 3. Mock Queue
# ============================================================
class MockQueue:
    def __init__(self):
        self.queues: Dict[str, List[Dict[str, Any]]] = {}
        self.published_count = 0
        self.consumed_count = 0
        self.crashed = False

    def publish(self, routing_key, body):
        if self.crashed:
            return
        self.queues.setdefault(routing_key, []).append(body)
        self.published_count += 1

    def drain(self, routing_key):
        msgs = self.queues.get(routing_key, [])
        self.queues[routing_key] = []
        self.consumed_count += len(msgs)
        return msgs

    def pending(self, routing_key):
        return len(self.queues.get(routing_key, []))

    def total_pending(self):
        return sum(len(q) for q in self.queues.values())


# ============================================================
# 4. 故障注入开关
# ============================================================
class FailureInjector:
    def __init__(self):
        self.bad_json_rate = 0.0
        self.timeout_rate = 0.0
        self.judge_pass_rate = 1.0
        self.worker_crash = False
        self.duplicate_mode = False
        self.json_failures = 0
        self.timeout_failures = 0
        self.crash_count = 0
        self.judge_failures = 0
        self.duplicate_messages = 0

    def should_bad_json(self):
        return random.random() < self.bad_json_rate

    def should_timeout(self):
        return random.random() < self.timeout_rate

    def should_judge_pass(self):
        return random.random() < self.judge_pass_rate

    def reset(self):
        self.bad_json_rate = 0.0
        self.timeout_rate = 0.0
        self.judge_pass_rate = 1.0
        self.worker_crash = False
        self.duplicate_mode = False
        self.json_failures = 0
        self.timeout_failures = 0
        self.crash_count = 0
        self.judge_failures = 0
        self.duplicate_messages = 0


# ============================================================
# 5. 上下文对象
# ============================================================
class LoadTestContext:
    def __init__(self):
        self.redis = MockRedis()
        self.db = MockDB()
        self.queue = MockQueue()
        self.injector = FailureInjector()
        self.step_executions: Dict[str, Dict[str, int]] = {}

    def step_stat(self, step_id):
        return self.step_executions.setdefault(
            step_id, {"total": 0, "success": 0, "failed": 0, "json_failed": 0}
        )

    def reset(self):
        self.redis = MockRedis()
        self.db = MockDB()
        self.queue = MockQueue()
        self.injector.reset()
        self.step_executions = {}


# ============================================================
# 6. 初始化入口
# ============================================================
_GLOBAL_CTX: Optional[LoadTestContext] = None


def init_mock_infra(seed: int = 42) -> LoadTestContext:
    """初始化 mock 设施，并 monkey-patch app.services 中的真实函数。"""
    global _GLOBAL_CTX
    random.seed(seed)

    ctx = LoadTestContext()
    _GLOBAL_CTX = ctx
    _install_monkey_patches(ctx)
    return ctx


def _install_monkey_patches(ctx: LoadTestContext) -> None:
    """把所有 monkey-patch 应用到 app.* 模块

    注意：调用者必须先 import 所有 app.* 模块，再调用本函数。
    """
    import app.services.idempotency as _idem
    import app.services.retry as _retry
    import app.services.queue as _queue
    import app.db.database as _db
    import app.services.orchestrator as _orch
    import app.services.llm_client as _llm
    import app.agents.base as _agent_base
    import app.services.tracing as _tracing  # noqa

    # ---- idempotency ----
    async def mock_acquire_idempotent(task_id, step_id, *, ttl=None):
        key = _idem.idempotent_key(task_id, step_id)
        marker = json.dumps({"ts": int(time.time()), "step_id": step_id})
        res = await ctx.redis.set(name=key, value=marker, nx=True, ex=ttl or 86400)
        if res:
            ctx.redis.idempotent_acquires += 1
            return True
        ctx.redis.idempotent_rejected += 1
        return False

    async def mock_release_idempotent(task_id, step_id):
        await ctx.redis.delete(_idem.idempotent_key(task_id, step_id))

    async def mock_is_idempotent_held(task_id, step_id):
        return await ctx.redis.exists(_idem.idempotent_key(task_id, step_id)) > 0

    async def mock_mark_message_seen(message_id):
        key = _idem.dedup_message_key(message_id)
        res = await ctx.redis.set(name=key, value="1", nx=True, ex=3600)
        if res:
            ctx.redis.dedup_seen += 1
            return True
        ctx.redis.dedup_dedup += 1
        return False

    _idem.acquire_idempotent = mock_acquire_idempotent
    _idem.release_idempotent = mock_release_idempotent
    _idem.is_idempotent_held = mock_is_idempotent_held
    _idem.mark_message_seen = mock_mark_message_seen
    _orch.acquire_idempotent = mock_acquire_idempotent

    # ---- queue ----
    class MockQueueClient:
        async def connect(self):
            pass

        async def close(self):
            pass

        async def publish(self, routing_key, body):
            ctx.queue.publish(routing_key, body)

        async def publish_step(self, task_id, step_id, payload):
            body = {
                "task_id": task_id,
                "step_id": step_id,
                "payload": payload,
                "ts": time.time(),
            }
            ctx.queue.publish(f"ad_task.{step_id}", body)

        async def publish_dead_letter(self, task_id, step_id, payload):
            body = {"task_id": task_id, "step_id": step_id, "payload": payload}
            ctx.queue.publish("ad_task.dead_letter", body)

    _mock_queue_instance = MockQueueClient()
    _queue.QueueClient = MockQueueClient
    _queue.get_queue_client = lambda: _mock_queue_instance
    _orch.get_queue_client = lambda: _mock_queue_instance

    # 修复：orchestrator 是单例，__init__ 时已经把 self.queue 设为真实的 queue
    # 即使 patch 了 get_queue_client，老的实例的 self.queue 仍是 None（如果还没连过）
    # 强制给 orchestrator 单例重新设置 queue
    try:
        orch_singleton = _orch.get_orchestrator()
        orch_singleton.queue = _mock_queue_instance
    except Exception:
        pass
    # 清掉单例缓存，下次 get_orchestrator() 会用新的 queue
    _orch._orch = None

    # ---- database.session_scope ----
    @contextmanager
    def mock_session_scope():
        """返回 MockSession 而不是 None，让 db.query() 等能链式调用"""
        yield MockSession(ctx.db)

    _db.session_scope = mock_session_scope
    _orch.session_scope = mock_session_scope
    _idem.session_scope = mock_session_scope
    _retry.session_scope = mock_session_scope

    # ---- retry ----
    def mock_send_to_dead_letter(task_id, step_id, failure_reason, input_payload,
                                  last_output, retry_count, error_message):
        ctx.db.add_dead_letter(MockDeadLetter(task_id, step_id, failure_reason, retry_count))
        if task_id in ctx.db.tasks:
            ctx.db.tasks[task_id].status = "dead_letter"
            ctx.db.tasks[task_id].last_failure_reason = failure_reason

    _retry.send_to_dead_letter = mock_send_to_dead_letter
    _orch.send_to_dead_letter = mock_send_to_dead_letter

    def mock_mark_task_retrying(task_id, failure_reason, error_message):
        t = ctx.db.tasks.get(task_id)
        if t:
            t.retry_count += 1
            t.last_failure_reason = failure_reason
            t.status = "retrying"
        return t.retry_count if t else 0

    _retry.mark_task_retrying = mock_mark_task_retrying
    _orch.mark_task_retrying = mock_mark_task_retrying

    # ---- LLM client ----
    from app.services.llm_client import LLMClient

    original_init = LLMClient.__init__

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.use_mock = True

    LLMClient.__init__ = patched_init

    # 项目 bug：base.py 调用 generate_json 时传了 step_id kwarg，
    # 但原函数没接收。我们 wrap 一下 accept 所有 kwargs。
    original_generate_json = LLMClient.generate_json

    async def patched_generate_json(self, prompt, *, system_prompt="", model=None,
                                     temperature=0.7, max_tokens=1024, prompt_version="v1.0",
                                     step_id=None, **extra):
        return await original_generate_json(
            self, prompt,
            system_prompt=system_prompt, model=model,
            temperature=temperature, max_tokens=max_tokens,
            prompt_version=prompt_version,
            step_id=step_id,
        )

    LLMClient.generate_json = patched_generate_json

    original_generate_text = LLMClient.generate_text

    async def patched_generate_text(self, prompt, *, system_prompt="", model=None,
                                     temperature=0.5, max_tokens=2048, prompt_version="v1.0",
                                     **extra):
        return await original_generate_text(
            self, prompt,
            system_prompt=system_prompt, model=model,
            temperature=temperature, max_tokens=max_tokens,
            prompt_version=prompt_version,
        )

    LLMClient.generate_text = patched_generate_text

    async def patched_mock_generate(self, prompt, system_prompt, model, **kwargs):
        await _llm._fake_async()

        if ctx.injector.should_timeout():
            ctx.injector.timeout_failures += 1
            from app.services.llm_client import LLMTimeoutError
            raise LLMTimeoutError("mock timeout")

        p = prompt.lower()

        if "score" in p and ("judge" in p or "评估" in p):
            if not ctx.injector.should_judge_pass():
                ctx.injector.judge_failures += 1
                eval_data = {
                    "score": 55,
                    "passed": False,
                    "issues": [{"type": "SELLING_POINT_DRIFT", "detail": "mock eval fail"}],
                    "risk_level": "medium",
                    "suggested_fix": "regenerate hook",
                }
            else:
                eval_data = {
                    "score": 87,
                    "passed": True,
                    "issues": [],
                    "risk_level": "low",
                    "suggested_fix": "",
                }
            content = json.dumps(eval_data, ensure_ascii=False)
            return content, max(len(prompt) // 4, 50), max(len(content) // 4, 50)

        if ctx.injector.should_bad_json():
            ctx.injector.json_failures += 1
            content = '{"hook": "test", "problem": "missing close'
            return content, max(len(prompt) // 4, 50), max(len(content) // 4, 50)

        # 优先用 step_id (kwargs 里传过来的)
        step_id = kwargs.get("step_id") or ""
        MOCK_BY_STEP = {
            "product_analysis": _llm.MOCK_PRODUCT_ANALYSIS,
            "script_generation": _llm.MOCK_SCRIPT,
            "storyboard_planning": _llm.MOCK_STORYBOARD,
            "material_suggestion": _llm.MOCK_MATERIALS,
            "quality_evaluation": _llm.MOCK_EVALUATION if hasattr(_llm, "MOCK_EVALUATION") else _llm.MOCK_PRODUCT_ANALYSIS,
            "repair": _llm.MOCK_PRODUCT_ANALYSIS,
        }
        if step_id in MOCK_BY_STEP:
            data = MOCK_BY_STEP[step_id]
        elif "storyboard" in p or "分镜" in p or "camera_shot" in p:
            data = _llm.MOCK_STORYBOARD
        elif "material_keyword" in p or "mock_library" in p:
            data = _llm.MOCK_MATERIALS
        elif "full_script" in p or ("hook" in p and "cta" in p):
            data = _llm.MOCK_SCRIPT
        elif "pain_points" in p or "core_selling_points" in p or "商品理解" in p:
            data = _llm.MOCK_PRODUCT_ANALYSIS
        elif "repair" in p or "修复" in p:
            data = _llm.MOCK_SCRIPT
        else:
            data = _llm.MOCK_PRODUCT_ANALYSIS

        content = json.dumps(data, ensure_ascii=False)
        return content, max(len(prompt) // 4, 50), max(len(content) // 4, 50)

    LLMClient._mock_generate = patched_mock_generate

    # ---- orchestrator: 把写库的 helper 全换成 mock ----
    def _write_task_to_db(task_id, status):
        t = ctx.db.tasks.get(task_id)
        if t:
            t.status = status
            if status in ("success", "failed", "dead_letter", "manual_review"):
                t.finished_at = time.time()

    def _write_step_to_db(task_id, step_id, status, **kwargs):
        s = ctx.db.get_step(task_id, step_id)
        if s:
            s.status = status
            for k, v in kwargs.items():
                setattr(s, k, v)

    async def patched_create_task(self, product):
        from app.services.tracing import generate_task_id, generate_trace_id
        from app.core.state_machine import WORKFLOW_STEPS, STEP_NAME_DISPLAY

        # 反馈重生: 复用上次的 evaluation 反馈
        feedback_for_task_id = product.get("feedback_for_task_id")
        style_override = product.get("style_override")
        feedback_str = ""
        history_override: Dict[str, Any] = {}
        start_step = WORKFLOW_STEPS[0]

        if feedback_for_task_id:
            ev = None
            for e in reversed(ctx.db.evaluations):
                if e.task_id == feedback_for_task_id:
                    ev = e
                    break
            if ev is not None:
                issues_text = "\n".join(
                    (i.get("detail") if isinstance(i, dict) else str(i))
                    for i in (ev.issues or [])
                )
                feedback_str = (
                    f"score={ev.score}\n"
                    f"issues={issues_text}\n"
                    f"suggested_fix={getattr(ev, 'suggested_fix', '') or ''}"
                )
            hist_step = ctx.db.get_step(feedback_for_task_id, "product_analysis")
            if hist_step and hist_step.output_payload:
                history_override["product_analysis"] = hist_step.output_payload
            start_step = "script_generation"

        if style_override:
            product = {**product, "style": style_override}

        task_id = generate_task_id()
        trace_id = generate_trace_id()
        ctx.db.add_task(MockTask(task_id=task_id, trace_id=trace_id,
                                  status="created", product=product))
        for step_id in WORKFLOW_STEPS:
            ctx.db.add_step(MockStep(task_id, step_id,
                                      STEP_NAME_DISPLAY.get(step_id, step_id)))
        payload = {
            "task_id": task_id,
            "trace_id": trace_id,
            "product": product,
            "history": history_override,
            "attempt": 1,
        }
        if feedback_str:
            payload["failure_feedback"] = feedback_str
        await self.queue.publish_step(task_id, start_step, payload)
        return task_id

    def patched_transition_task(self, task_id, to_status):
        _write_task_to_db(task_id, to_status)

    def patched_transition_step(self, task_id, step_id, to_status):
        _write_step_to_db(task_id, step_id, to_status,
                          started_at=time.time() if to_status == "running" else None)

    async def patched_finalize_task(self, task_id, status="success", score=None):
        _write_task_to_db(task_id, status)
        if score is not None:
            t = ctx.db.tasks.get(task_id)
            if t:
                t.output_payload["quality_score"] = score
        # 同时记 trace
        ctx.db.event_log.append({"type": "task.finalize", "task_id": task_id, "status": status})

    _orch.WorkflowOrchestrator.create_task = patched_create_task
    _orch.WorkflowOrchestrator._transition_task = patched_transition_task
    _orch.WorkflowOrchestrator._transition_step = patched_transition_step
    _orch.WorkflowOrchestrator._finalize_task = patched_finalize_task

    # 同时把 orchestrator 内部的 from-import 也覆盖掉，避免冗余
    # (因为 _install_monkey_patches 内部已经把 acquire_idempotent 等重置了)

    # ---- patch app.agents.base 里的 session_scope（_update_metric 用） ----
    _agent_base.session_scope = mock_session_scope
    _tracing.session_scope = mock_session_scope

    # 直接 patch 整个 _update_metric 方法，让它 no-op
    def noop_update_metric(self, success, json_failed, token_cost=0, latency_ms=0):
        step_id = self.step_id
        st = ctx.step_stat(step_id)
        st["total"] += 1
        if success:
            st["success"] += 1
        else:
            st["failed"] += 1
        if json_failed:
            st["json_failed"] += 1

    _agent_base.BaseAgent._update_metric = noop_update_metric


def get_context() -> LoadTestContext:
    """获取全局 mock context"""
    global _GLOBAL_CTX
    if _GLOBAL_CTX is None:
        _GLOBAL_CTX = init_mock_infra()
    return _GLOBAL_CTX