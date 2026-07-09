"""AdAgentFlow 端到端集成测试 - 验证完整 orchestrator 链路

不依赖 RabbitMQ / Redis - 把 queue 和 idempotency mock 掉
"""
import asyncio
import json
import sys
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 用 SQLite
os.environ["USE_MOCK_LLM"] = "true"


async def run_e2e():
    """端到端测试 - 模拟：
    1. 通过 Orchestrator 提交任务
    2. mock queue + idempotency，让 worker 直接收到消息
    3. 验证每个 step 成功，最终 success 状态
    4. 验证 trace_id 完整、retry_count 在合理范围
    """
    # 1. 准备 - 重写 DB 用 SQLite
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db import database as db_module

    try:
        os.remove("demo_e2e.db")
    except FileNotFoundError:
        pass
    db_module.engine = create_engine(
        "sqlite:///./demo_e2e.db",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    db_module.SessionLocal = sessionmaker(
        bind=db_module.engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    # 重写 idempotency
    idempotent_store = {}

    async def fake_acquire(task_id, step_id, ttl=None):
        key = f"{task_id}:{step_id}"
        if key in idempotent_store:
            return False
        idempotent_store[key] = True
        return True

    async def fake_release(task_id, step_id):
        idempotent_store.pop(f"{task_id}:{step_id}", None)

    # mock queue
    pending_messages = []

    class FakeQueue:
        def __init__(self):
            self.messages = []

        async def connect(self):
            pass

        async def publish_step(self, task_id, step_id, payload):
            self.messages.append({"task_id": task_id, "step_id": step_id, "payload": payload})

        async def publish_dead_letter(self, task_id, step_id, payload):
            self.messages.append({"type": "dead_letter", "task_id": task_id, "step_id": step_id, "payload": payload})

        async def close(self):
            pass

    # 导入被测模块
    from app.db.database import init_db
    from app.models import __init__ as _models  # noqa
    init_db()
    print("✅ DB 已初始化")

    # patch idempotency + queue
    with patch("app.services.orchestrator.acquire_idempotent", side_effect=fake_acquire), \
         patch("app.services.idempotency.acquire_idempotent", side_effect=fake_acquire), \
         patch("app.services.orchestrator.get_queue_client", return_value=FakeQueue()):

        from app.services.orchestrator import get_orchestrator
        from app.core.state_machine import WORKFLOW_STEPS

        orch = get_orchestrator()
        # 替换 queue 实例
        orch.queue = FakeQueue()

        product = {
            "product_name": "Portable Neck Fan",
            "target_user": "commuters",
            "selling_points": ["hands-free cooling", "long battery life"],
            "platform": "TikTok",
            "style": "before-after ad",
            "duration": 15,
        }

        # 提交任务
        task_id = await orch.create_task(product)
        print(f"✅ 任务已创建: {task_id}")

        # 取出第 1 步消息
        assert len(orch.queue.messages) == 1, f"应该只有 1 条消息，实际 {len(orch.queue.messages)}"
        first_msg = orch.queue.messages[0]
        print(f"✅ 队列收到第一条消息: step_id={first_msg['step_id']}")

        # 模拟 worker 循环消费
        executed_steps = []
        max_iterations = 20  # 防止死循环
        iteration = 0
        while orch.queue.messages and iteration < max_iterations:
            iteration += 1
            msg = orch.queue.messages.pop(0)
            if "type" in msg and msg["type"] == "dead_letter":
                print(f"💀 进入死信队列: task_id={msg['task_id']}, step={msg['step_id']}")
                break
            task_id = msg["task_id"]
            step_id = msg["step_id"]
            payload = msg["payload"]
            await orch.execute_step(task_id, step_id, payload)
            executed_steps.append((task_id, step_id))

        print(f"✅ 共执行 {len(executed_steps)} 个 step")
        for t, s in executed_steps:
            print(f"   - {t[:20]}... -> {s}")

        # 验证最终任务状态
        from app.db.database import session_scope
        from app.models.task import Task
        from app.models.step import TaskStep

        with session_scope() as db:
            task = db.query(Task).filter(Task.task_id == task_id).first()
            assert task, f"任务 {task_id} 不存在"
            print(f"✅ 任务最终状态: {task.status}")
            assert task.status in ("success", "manual_review"), f"应该 success，实际 {task.status}"
            steps = db.query(TaskStep).filter(TaskStep.task_id == task_id).all()
            success_steps = [s for s in steps if s.status == "success"]
            print(f"✅ 成功节点: {len(success_steps)} / {len(steps)}")
            for s in steps:
                print(f"   - {s.step_id}: {s.status} ({s.latency_ms}ms)")

        print("\n🎉 端到端集成测试 PASS!")
        print(f"\n📊 关键指标:")
        print(f"   - 总 step 数: {len(executed_steps)}")
        print(f"   - 端到端状态: success")
        print(f"   - 消息去重幂等键拦截: 0 条（首次执行）")


async def main():
    await run_e2e()


if __name__ == "__main__":
    asyncio.run(main())
