"""反馈重生: 复用上次的 evaluation 反馈"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.evaluation import EvaluationResult
from app.services.orchestrator import get_orchestrator
from scripts.helpers.mock_infra import (
    LoadTestContext,
    MockEvaluation,
    MockSession,
    MockStep,
)

pytestmark = pytest.mark.asyncio


def _drain_queue(ctx: LoadTestContext, routing_key: str):
    return ctx.queue.drain(routing_key)


def _topic(step_id: str) -> str:
    return f"ad_task.{step_id}"


async def test_create_task_with_feedback_carries_eval_into_payload(
    mock_ctx: LoadTestContext, monkeypatch
):
    """feedback_for_task_id 非空时, queue payload 应包含 score/issues/suggested_fix,
    且 start_step=script_generation (跳过 product_analysis), style_override 生效."""
    orch = get_orchestrator()

    # 1) 准备一个历史 task + 它的 evaluation
    product = {
        "product_name": "Fan",
        "target_user": "commuters",
        "selling_points": ["cool", "light"],
        "platform": "TikTok",
        "style": "dramatic",
        "duration": 15,
    }
    old_task_id = await orch.create_task(product)

    # 把 evaluation 直接灌进 mock db（与 _handle_evaluation 写入效果一致）
    mock_ctx.db.evaluations.append(
        MockEvaluation(
            task_id=old_task_id,
            score=55,
            passed=False,
            risk_level="medium",
            issues=[{"type": "SELLING_POINT_DRIFT", "detail": "卖点不够直观"}],
        )
    )
    # 把 suggested_fix 写在 output_payload 之后；mock 版的 _handle_evaluation 不存 suggested_fix，
    # 但 patched_create_task 会查 mock_db 上对应 evaluation 记录的 suggested_fix（如果存在）。
    # 由于 MockEvaluation 不含 suggested_fix，我们在测试里把它附在 evaluation 对象上。
    mock_ctx.db.evaluations[-1].suggested_fix = "在 hook 里直接喊出产品名"
    mock_ctx.db.evaluations[-1].step_id = "quality_evaluation"

    # 同时给 create_task 自动插入的 product_analysis MockStep 填上 output_payload，
    # 让 patched_create_task 把它塞进 history["product_analysis"]。
    existing_pa = mock_ctx.db.get_step(old_task_id, "product_analysis")
    assert existing_pa is not None, "create_task 应已插入 product_analysis 占位"
    existing_pa.output_payload = {
        "pain_points": ["hot in summer"],
        "core_selling_points": ["cool"],
    }

    # 清掉 create_task 默认派发的 product_analysis 消息，避免断言混淆
    _drain_queue(mock_ctx, _topic("product_analysis"))

    # 2) 用 feedback_for_task_id + style_override 提交新任务
    new_task_id = await orch.create_task(
        {**product, "feedback_for_task_id": old_task_id, "style_override": "humor"}
    )

    # 3) 验证：start_step 跳过 product_analysis，应只派 script_generation
    pa_msgs = _drain_queue(mock_ctx, _topic("product_analysis"))
    assert pa_msgs == [], "feedback_for_task_id 非空时不应再派 product_analysis"

    sg_msgs = _drain_queue(mock_ctx, _topic("script_generation"))
    assert len(sg_msgs) == 1, f"script_generation 应被派发 1 条, 实际 {len(sg_msgs)}"
    body = sg_msgs[0]
    assert body["step_id"] == "script_generation"

    payload = body["payload"]
    fb = payload.get("failure_feedback", "")
    assert "score=55" in fb, f"failure_feedback 应包含 score=55, 实际: {fb!r}"
    assert "卖点不够直观" in fb, f"failure_feedback 应包含 issue detail, 实际: {fb!r}"
    assert "在 hook 里直接喊出产品名" in fb, f"failure_feedback 应包含 suggested_fix, 实际: {fb!r}"

    # history 应包含上次的 product_analysis 输出
    assert "product_analysis" in payload["history"], "history 应包含 product_analysis"
    assert (
        payload["history"]["product_analysis"]["pain_points"] == ["hot in summer"]
    )

    # style_override 应覆盖 product.style
    assert payload["product"]["style"] == "humor", (
        f"style 应被覆盖为 humor, 实际 {payload['product']['style']!r}"
    )

    assert new_task_id != old_task_id


async def test_create_task_without_feedback_starts_at_product_analysis(
    mock_ctx: LoadTestContext,
):
    """不带 feedback_for_task_id 时, 仍然从 product_analysis 开始, 无 failure_feedback。"""
    orch = get_orchestrator()
    product = {
        "product_name": "Fan",
        "target_user": "commuters",
        "selling_points": ["cool"],
        "platform": "TikTok",
        "style": "dramatic",
        "duration": 15,
    }
    task_id = await orch.create_task(product)

    pa_msgs = _drain_queue(mock_ctx, _topic("product_analysis"))
    assert len(pa_msgs) == 1
    payload = pa_msgs[0]["payload"]
    assert pa_msgs[0]["step_id"] == "product_analysis"
    assert "failure_feedback" not in payload
    assert payload["product"]["style"] == "dramatic"
    assert task_id.startswith("task_")


async def test_submit_task_request_accepts_new_fields():
    """SubmitTaskRequest 应支持 feedback_for_task_id / style_override 字段。"""
    from app.api.task_router import SubmitTaskRequest

    req = SubmitTaskRequest(
        product_name="Fan",
        feedback_for_task_id="task_old",
        style_override="humor",
    )
    assert req.feedback_for_task_id == "task_old"
    assert req.style_override == "humor"
    dumped = req.model_dump()
    assert dumped["feedback_for_task_id"] == "task_old"
    assert dumped["style_override"] == "humor"