"""Light Worker - 处理 5 个轻量 Agent 节点

启动脚本: python -m app.workers.light_worker
"""
import asyncio
import signal
import json
from typing import Optional, List

import aio_pika
from aio_pika.abc import AbstractIncomingMessage

from app.core.config import settings
from app.core.logging import get_logger
from app.services.queue import (
    QueueClient,
    WORKFLOW_TOPICS,
    EXCHANGE_NAME,
    get_queue_client,
    close_queue_client,
)
from app.services.orchestrator import get_orchestrator

logger = get_logger()

LIGHT_STEPS = [
    "ad_task.product_analysis",
    "ad_task.script_generation",
    "ad_task.storyboard_planning",
    "ad_task.material_suggestion",
    "ad_task.quality_evaluation",
]


class LightWorker:
    """异步消费 Worker - 监听 5 个 topic，每个消息调用 orchestrator.execute_step"""

    def __init__(self):
        self.queue = get_queue_client()
        self.orchestrator = get_orchestrator()
        self.concurrency = int(__import__("os").environ.get("WORKER_CONCURRENCY", "4"))
        self._running = False
        self._consumer_tasks: List[asyncio.Task] = []

    async def run(self):
        """启动消费循环"""
        await self.queue.connect()
        self._running = True

        channel = self.queue._channel
        # 设置 prefetch
        await channel.set_qos(prefetch_count=self.concurrency * 2)

        # 创建任务：每个 topic 一个 consumer
        for topic in LIGHT_STEPS:
            t = asyncio.create_task(self._consume_topic(topic))
            self._consumer_tasks.append(t)

        logger.info(
            f"Light Worker 已启动，并发度={self.concurrency}, 监听 {len(LIGHT_STEPS)} 个 topic"
        )

        # 等待
        try:
            await asyncio.gather(*self._consumer_tasks)
        except asyncio.CancelledError:
            logger.info("Light Worker 收到取消信号，停止消费")

    async def _consume_topic(self, topic: str):
        """单 topic 的消费循环"""
        queue_name = f"{topic}.queue"
        channel = self.queue._channel
        queue = await channel.get_queue(queue_name, ensure=False)
        if queue is None:
            logger.warning(f"队列 {queue_name} 不存在，等待 ...")
            await asyncio.sleep(2)
            return
        # 重试 3 次直到队列就绪
        for _ in range(5):
            if queue is not None:
                break
            await asyncio.sleep(1)
            queue = await channel.get_queue(queue_name, ensure=False)

        async with queue.iterator() as q_iter:
            async for message in q_iter:
                if not self._running:
                    break
                await self._handle_message(message, topic)

    async def _handle_message(self, message: AbstractIncomingMessage, topic: str):
        """处理单条消息 - 含异常兜底，保证不会卡死 worker"""
        async with message.process(requeue=False):
            try:
                body = json.loads(message.body.decode("utf-8"))
            except Exception as e:
                logger.error(f"消息解析失败: {e}, ack 并丢弃")
                return
            task_id = body.get("task_id")
            step_id = body.get("step_id")
            payload = body.get("payload", {})
            logger.info(f"[{step_id}] 收到任务 {task_id}, attempt={payload.get('attempt', 1)}")
            try:
                await self.orchestrator.execute_step(task_id, step_id, payload)
            except Exception as e:
                logger.error(f"execute_step 异常: {e}\n{__import__('traceback').format_exc()}")

    async def stop(self):
        self._running = False
        for t in self._consumer_tasks:
            t.cancel()
        await close_queue_client()


async def main():
    worker = LightWorker()
    loop = asyncio.get_event_loop()

    def _shutdown():
        logger.info("收到 SIGINT/SIGTERM, 停止 worker ...")
        asyncio.create_task(worker.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass  # Windows 不支持
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
