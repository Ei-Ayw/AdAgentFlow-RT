"""Task router (app/api/task_router.py) 单元测试。

覆盖：GET /api/v1/tasks/ 列表端点返回的字段集合。
- 回归测试：list 必须返回 duration 字段（前端 TaskCard.js 依赖它）。
- 回归测试：detail 必须返回 selling_points 字段（前端 TaskDetailPage 重生依赖它）。
"""
from __future__ import annotations

import pytest


SAMPLE_TASK_ROW = {
    "task_id": "task_test_duration_001",
    "trace_id": "trace_test_001",
    "status": "success",
    "product_name": "Portable Neck Fan",
    "platform": "TikTok",
    "style": "dramatic before-after ad",
    "duration": 15,
    "target_user": "commuters",
    "selling_points": ["hands-free cooling", "long battery life"],
    "input_payload": {
        "product_assets": ["/uploads/fan-front.jpg"],
        "reference_video": "/uploads/reference.mp4",
    },
    "retry_count": 0,
    "max_retry": 3,
    "last_failure_reason": None,
}


@pytest.fixture()
def seeded_task(sqlite_db):
    """在 sqlite 测试库中插入一条 task 行，供 list endpoint 读取。"""
    from app.models.task import Task

    SessionLocal = sqlite_db["session_local"]
    with SessionLocal() as session:
        row = Task(**SAMPLE_TASK_ROW)
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


@pytest.fixture()
def seeded_step(sqlite_db, seeded_task):
    """插入带业务输出的步骤，验证详情接口可供前端渲染结果卡。"""
    from app.models.step import TaskStep

    SessionLocal = sqlite_db["session_local"]
    with SessionLocal() as session:
        row = TaskStep(
            task_id=seeded_task.task_id,
            step_id="script_generation",
            step_name="广告脚本",
            status="success",
            retry_count=0,
            output_payload={"hook": "3 秒抓住注意力"},
        )
        session.add(row)
        session.commit()
    return row


class TestListTasks:
    def test_list_includes_duration(self, sqlite_db, seeded_task):
        """回归：list endpoint 必须返回 duration 字段（TaskCard.js 渲染依赖）。"""
        from app.api.task_router import list_tasks

        db = sqlite_db["session_local"]()
        try:
            response = list_tasks(status=None, limit=20, offset=0, db=db)
        finally:
            db.close()

        assert "items" in response
        assert len(response["items"]) >= 1

        item = response["items"][0]
        assert "duration" in item, (
            "GET /api/v1/tasks/ 必须返回 duration 字段，"
            "否则 TaskCard.js 会渲染 'undefineds'。"
        )
        assert item["duration"] == 15


class TestGetTaskDetail:
    def test_detail_includes_selling_points(self, sqlite_db, seeded_task):
        """回归：detail endpoint 必须返回 selling_points 字段
        （TaskDetailPage.js 重生操作需要把 selling_points 透传给新 task）。
        """
        from app.api.task_router import get_task

        db = sqlite_db["session_local"]()
        try:
            response = get_task(task_id=seeded_task.task_id, db=db)
        finally:
            db.close()

        assert response.task_id == seeded_task.task_id
        assert "selling_points" in response.model_dump(), (
            "GET /api/v1/tasks/{id} 必须返回 selling_points 字段，"
            "否则 TaskDetailPage 重生时 selling_points 会变空数组。"
        )
        assert response.selling_points == ["hands-free cooling", "long battery life"]

    def test_detail_includes_target_user(self, sqlite_db, seeded_task):
        """回归：detail endpoint 必须返回 target_user 字段
        （TaskDetailPage.js 重生操作需要把 target_user 透传给新 task）。
        """
        from app.api.task_router import get_task

        db = sqlite_db["session_local"]()
        try:
            response = get_task(task_id=seeded_task.task_id, db=db)
        finally:
            db.close()

        assert response.target_user == "commuters"

    def test_detail_step_includes_output_payload(self, sqlite_db, seeded_task, seeded_step):
        """回归：结果卡依赖每个 step 的 output_payload。"""
        from app.api.task_router import get_task

        db = sqlite_db["session_local"]()
        try:
            response = get_task(task_id=seeded_task.task_id, db=db)
        finally:
            db.close()

        assert len(response.steps) == 1
        assert response.steps[0].output_payload == {"hook": "3 秒抓住注意力"}

    def test_detail_includes_creation_assets(self, sqlite_db, seeded_task):
        from app.api.task_router import get_task

        db = sqlite_db["session_local"]()
        try:
            response = get_task(task_id=seeded_task.task_id, db=db)
        finally:
            db.close()

        assert response.product_assets == ["/uploads/fan-front.jpg"]
        assert response.reference_video == "/uploads/reference.mp4"
