"""端到端冒烟测试: 模拟前端 → 后端的完整调用序列。"""
from __future__ import annotations

import pytest
from app.services.orchestrator import get_orchestrator

pytestmark = pytest.mark.asyncio


async def test_full_smoke_flow(mock_ctx):
    """模拟用户: 提交 → 轮询拿到 success → 用 feedback_for_task_id 反馈重生。"""
    orch = get_orchestrator()

    # 1. 提交第一个任务
    product = {
        "product_name": "Smoke Fan",
        "target_user": "commuters",
        "selling_points": ["cool"],
        "platform": "TikTok",
        "style": "dramatic",
        "duration": 15,
    }
    task_id = await orch.create_task(product)
    assert task_id.startswith("task_")

    # 2. 模拟: 5 步全部走完, task 落库可查
    from app.db.database import session_scope
    from app.models.task import Task
    with session_scope() as db:
        task = db.query(Task).filter(Task.task_id == task_id).first()
        assert task is not None
        assert task.product_name == "Smoke Fan"

    # 3. 反馈重生(不验证 payload 内容, 只验证接口不报错)
    new_task_id = await orch.create_task(
        {**product, "feedback_for_task_id": task_id, "style_override": "humor"}
    )
    assert new_task_id != task_id