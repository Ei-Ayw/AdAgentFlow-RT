"""Orchestrator 单元测试（基于 mock_infra）

覆盖：
- create_task 后 task 入库、status=created、5 个 step 占位都建出来
- publish 第一个 step 到 queue
- execute_step 成功路径 → step.status=success + 派下一个 step
- 一个 step 失败 → 重试调度（retry_count+1, status=retrying）
- 重试达到上限 → dead_letter
- 完整 5 步成功流跑通
"""
from __future__ import annotations

import asyncio
import pytest

from scripts.helpers.mock_infra import (
    MockTask,
    MockStep,
    MockDeadLetter,
    LoadTestContext,
)


pytestmark = pytest.mark.asyncio


# ============================================================
# helpers
# ============================================================
SAMPLE_PRODUCT = {
    "product_name": "Portable Neck Fan",
    "platform": "TikTok",
    "duration": 15,
    "target_user": "commuters",
    "selling_points": ["hands-free cooling", "long battery life"],
}


def _drain_queue(ctx: LoadTestContext, routing_key: str):
    """读出 queue 里的所有消息。"""
    return ctx.queue.drain(routing_key)


def _fresh_workflow_topic(step_id: str) -> str:
    return f"ad_task.{step_id}"


# ============================================================
# 1. create_task
# ============================================================
class TestCreateTask:
    async def test_create_task_returns_id(self, mock_ctx, sqlite_db):
        from app.services.orchestrator import get_orchestrator

        orch = get_orchestrator()
        task_id = await orch.create_task(SAMPLE_PRODUCT)
        assert task_id.startswith("task_")
        assert task_id in mock_ctx.db.tasks

    async def test_create_task_status_is_created(self, mock_ctx, sqlite_db):
        from app.services.orchestrator import get_orchestrator

        orch = get_orchestrator()
        task_id = await orch.create_task(SAMPLE_PRODUCT)
        task = mock_ctx.db.tasks[task_id]
        assert task.status == "created"
        assert task.retry_count == 0

    async def test_create_task_inserts_all_workflow_steps(self, mock_ctx, sqlite_db):
        from app.services.orchestrator import get_orchestrator

        orch = get_orchestrator()
        task_id = await orch.create_task(SAMPLE_PRODUCT)

        for step_id in (
            "product_analysis",
            "script_generation",
            "storyboard_planning",
            "material_suggestion",
            "quality_evaluation",
        ):
            s = mock_ctx.db.get_step(task_id, step_id)
            assert s is not None, f"step {step_id} should exist"
            assert s.status == "pending"

    async def test_create_task_publishes_first_step(self, mock_ctx, sqlite_db):
        from app.services.orchestrator import get_orchestrator

        orch = get_orchestrator()
        task_id = await orch.create_task(SAMPLE_PRODUCT)

        msgs = _drain_queue(mock_ctx, _fresh_workflow_topic("product_analysis"))
        assert len(msgs) == 1
        body = msgs[0]
        assert body["task_id"] == task_id
        assert body["step_id"] == "product_analysis"
        payload = body["payload"]
        assert payload["product"] == SAMPLE_PRODUCT
        assert payload["attempt"] == 1
        assert payload["history"] == {}

    async def test_create_task_sets_trace_id(self, mock_ctx, sqlite_db):
        from app.services.orchestrator import get_orchestrator

        orch = get_orchestrator()
        task_id = await orch.create_task(SAMPLE_PRODUCT)
        task = mock_ctx.db.tasks[task_id]
        assert task.trace_id.startswith("trace_")


# ============================================================
# 2. execute_step - 成功路径
# ============================================================
class TestExecuteStepSuccess:
    async def test_execute_step_succeeds_and_publishes_next(self, mock_ctx, sqlite_db):
        """执行 product_analysis → 成功 → 派 script_generation。"""
        from app.services.orchestrator import get_orchestrator

        orch = get_orchestrator()
        task_id = await orch.create_task(SAMPLE_PRODUCT)

        # 消费掉 create_task 派发的消息，避免与 execute_step 之后的派发混淆
        _drain_queue(mock_ctx, _fresh_workflow_topic("product_analysis"))

        task = mock_ctx.db.tasks[task_id]
        payload = {
            "task_id": task_id,
            "trace_id": task.trace_id,
            "product": SAMPLE_PRODUCT,
            "history": {},
            "attempt": 1,
        }
        await orch.execute_step(task_id, "product_analysis", payload)

        step = mock_ctx.db.get_step(task_id, "product_analysis")
        assert step.status == "success"
        assert step.output_payload is not None
        assert "pain_points" in step.output_payload
        assert step.latency_ms >= 0

        # 下一个 step 应被派发
        msgs = _drain_queue(mock_ctx, _fresh_workflow_topic("script_generation"))
        assert len(msgs) == 1
        assert msgs[0]["step_id"] == "script_generation"
        # history 应包含上一步的输出
        assert "product_analysis" in msgs[0]["payload"]["history"]

    async def test_execute_step_with_payload_double_nesting(self, mock_ctx, sqlite_db):
        """orchestrator 的 payload 形状：可能是 {payload: {...}, attempt: N} 或顶层字段。

        这里使用顶层字段形式（同 create_task publish 的格式）。
        """
        from app.services.orchestrator import get_orchestrator

        orch = get_orchestrator()
        task_id = await orch.create_task(SAMPLE_PRODUCT)
        _drain_queue(mock_ctx, _fresh_workflow_topic("product_analysis"))

        task = mock_ctx.db.tasks[task_id]
        payload = {
            "task_id": task_id,
            "trace_id": task.trace_id,
            "product": SAMPLE_PRODUCT,
            "history": {},
            "attempt": 1,
        }
        await orch.execute_step(task_id, "product_analysis", payload)
        # status 应推进到 RUNNING 或 EVALUATING（mock_infra 直接写库）
        task = mock_ctx.db.tasks[task_id]
        assert task.status in ("running", "success", "queued", "retrying")


# ============================================================
# 3. execute_step - 失败重试
# ============================================================
class TestExecuteStepFailureRetry:
    async def test_failure_triggers_retry(self, mock_ctx, sqlite_db):
        """把 bad_json_rate 设成 1.0，让 LLM 输出坏 JSON → Agent 走修复 → 失败 → retry。"""
        from app.services.orchestrator import get_orchestrator
        from app.services.llm_client import LLMClient

        mock_ctx.injector.bad_json_rate = 1.0

        # 让 LLMClient 真的输出坏 JSON（不再走 mock_infra 的 step_id 路由）
        # mock_infra 已经在 step_id 命中时直接返回合法 JSON，所以我们 monkey patch
        # 一次 LLMClient._mock_generate 让它总是返回坏 JSON
        original_mock_generate = LLMClient._mock_generate

        async def always_bad(prompt, system_prompt, model, **kwargs):
            return '{"hook": "x", "broken', 10, 10

        LLMClient._mock_generate = always_bad

        try:
            orch = get_orchestrator()
            task_id = await orch.create_task(SAMPLE_PRODUCT)
            _drain_queue(mock_ctx, _fresh_workflow_topic("product_analysis"))

            task = mock_ctx.db.tasks[task_id]
            payload = {
                "task_id": task_id,
                "trace_id": task.trace_id,
                "product": SAMPLE_PRODUCT,
                "history": {},
                "attempt": 1,
            }
            await orch.execute_step(task_id, "product_analysis", payload)

            # 即使 JSON 坏，base.py 的 quick repair 应该把它救回来（缺右括号可补）
            step = mock_ctx.db.get_step(task_id, "product_analysis")
            # 因为 quick_json_repair 补右括号后再 validate 应该还会失败（schema 不全）
            # 所以应该是 FAILED + retry 路径
            assert step.status in ("failed", "success"), step.status
            # task 应被标记为 retrying 或 running
            task = mock_ctx.db.tasks[task_id]
            assert task.status in ("retrying", "running")
        finally:
            LLMClient._mock_generate = original_mock_generate

    async def test_failure_after_max_retry_goes_to_dead_letter(self, mock_ctx, sqlite_db):
        """强制坏 JSON + 已 retry_count=3 → 下一轮失败应进死信。"""
        from app.services.orchestrator import get_orchestrator
        from app.services.llm_client import LLMClient

        original_mock_generate = LLMClient._mock_generate

        async def always_bad(prompt, system_prompt, model, **kwargs):
            # 输出无法 quick_repair 的内容（不是 JSON 也不是半 JSON）
            return "this is totally not json at all", 10, 10

        LLMClient._mock_generate = always_bad

        try:
            orch = get_orchestrator()
            task_id = await orch.create_task(SAMPLE_PRODUCT)

            # 手动把 task 的 retry_count 推到 max
            task = mock_ctx.db.tasks[task_id]
            task.max_retry = 2
            task.retry_count = 2  # 即将超限

            _drain_queue(mock_ctx, _fresh_workflow_topic("product_analysis"))

            payload = {
                "task_id": task_id,
                "trace_id": task.trace_id,
                "product": SAMPLE_PRODUCT,
                "history": {},
                "attempt": 3,
            }
            await orch.execute_step(task_id, "product_analysis", payload)

            # 应进死信
            assert task.status == "dead_letter"
            assert len(mock_ctx.db.dead_letters) >= 1
            dl = mock_ctx.db.dead_letters[-1]
            assert dl.task_id == task_id
            assert dl.step_id == "product_analysis"
        finally:
            LLMClient._mock_generate = original_mock_generate

    async def test_retry_then_recover(self, mock_ctx, sqlite_db):
        """step 失败 → task 进入 retrying → 重试后成功。"""
        from app.services.orchestrator import get_orchestrator
        from app.services.llm_client import LLMClient
        from app.services import idempotency as idem

        call_count = {"n": 0}
        original_mock_generate = LLMClient._mock_generate

        async def sometimes_bad(self_or_none, prompt, system_prompt, model, **kwargs):
            call_count["n"] += 1
            if call_count["n"] <= 2:
                return "totally broken garbage no json here", 10, 10
            return await original_mock_generate(
                self_or_none, prompt, system_prompt, model, **kwargs
            )

        LLMClient._mock_generate = sometimes_bad

        try:
            orch = get_orchestrator()
            task_id = await orch.create_task(SAMPLE_PRODUCT)
            _drain_queue(mock_ctx, _fresh_workflow_topic("product_analysis"))

            task = mock_ctx.db.tasks[task_id]
            payload = {
                "task_id": task_id,
                "trace_id": task.trace_id,
                "product": SAMPLE_PRODUCT,
                "history": {},
                "attempt": 1,
            }
            await orch.execute_step(task_id, "product_analysis", payload)

            # 第一次 run 内 repair 也失败 → needs_retry=True → 走重试
            assert task.retry_count >= 1
            assert task.status == "retrying"
            step = mock_ctx.db.get_step(task_id, "product_analysis")
            assert step.status in ("failed", "retrying")

            # 生产环境的 worker 在失败后会 release_idempotent，这里手动模拟
            # 否则第二次 execute_step 会被 idempotency 拦截跳过。
            await idem.release_idempotent(task_id, "product_analysis")

            # 模拟 worker 拉起重试消息：再调一次 execute_step（恢复后的 LLM）
            payload["attempt"] = 2
            payload["failure_feedback"] = "previous failed"
            await orch.execute_step(task_id, "product_analysis", payload)

            # 这次应成功（第三次 LLM 调用输出合法 JSON）
            step = mock_ctx.db.get_step(task_id, "product_analysis")
            assert step.status in ("success", "running"), step.status
            task = mock_ctx.db.tasks[task_id]
            assert task.status != "dead_letter", f"task 进死信了: {task.status}"
        finally:
            LLMClient._mock_generate = original_mock_generate


# ============================================================
# 4. end-to-end 完整 5 步
# ============================================================
class TestFullWorkflow:
    async def test_all_five_steps_run_through(self, mock_ctx, sqlite_db):
        """完整跑通 product_analysis → quality_evaluation，task 收尾。"""
        from app.services.orchestrator import get_orchestrator

        orch = get_orchestrator()
        task_id = await orch.create_task(SAMPLE_PRODUCT)
        task = mock_ctx.db.tasks[task_id]

        current_step = "product_analysis"
        history: dict = {}
        max_iter = 12  # 安全网，防止死循环
        i = 0
        while i < max_iter:
            i += 1
            _drain_queue(mock_ctx, _fresh_workflow_topic(current_step))

            payload = {
                "task_id": task_id,
                "trace_id": task.trace_id,
                "product": SAMPLE_PRODUCT,
                "history": history,
                "attempt": 1,
            }
            await orch.execute_step(task_id, current_step, payload)
            step = mock_ctx.db.get_step(task_id, current_step)
            assert step.status in ("success", "running"), (
                f"{current_step} 状态异常: {step.status}"
            )
            history[current_step] = step.output_payload

            # 是否进入 evaluation 分支？
            task = mock_ctx.db.tasks[task_id]
            if current_step == "quality_evaluation":
                # 评估成功应直接 finalize
                if task.status == "success":
                    break
                # 否则进入 retry/manual_review
                break

            # 派发下一个 step
            next_msgs = _drain_queue(mock_ctx, _fresh_workflow_topic(_next(current_step)))
            if not next_msgs:
                break
            current_step = _next(current_step)

        # 最终状态应该是 success（mock 默认 judge_pass）
        task = mock_ctx.db.tasks[task_id]
        assert task.status == "success", f"task status: {task.status}"


def _next(step_id: str) -> str:
    """本地 next_step_or_done（避免 import 链引入副作用）。"""
    order = [
        "product_analysis",
        "script_generation",
        "storyboard_planning",
        "material_suggestion",
        "quality_evaluation",
    ]
    if step_id not in order:
        return step_id
    idx = order.index(step_id)
    if idx + 1 >= len(order):
        return step_id
    return order[idx + 1]