"""Heavy Worker - 处理 repair / 视频生成 mock / 批量任务

启动: python -m app.workers.heavy_worker
"""
import asyncio
import signal
import json
from typing import List

import aio_pika
from aio_pika.abc import AbstractIncomingMessage

from app.core.config import settings
from app.core.logging import get_logger
from app.services.queue import get_queue_client, close_queue_client
from app.services.orchestrator import get_orchestrator

logger = get_logger()

HEAVY_TOPICS = [
    "ad_task.repair",
]


class HeavyWorker:
    def __init__(self):
        self.queue = get_queue_client()
        self.orchestrator = get_orchestrator()
        self.concurrency = int(__import__("os").environ.get("WORKER_CONCURRENCY", "2"))
        self._running = False
        self._consumer_tasks: List[asyncio.Task] = []

    async def run(self):
        await self.queue.connect()
        self._running = True
        channel = self.queue._channel
        await channel.set_qos(prefetch_count=self.concurrency * 2)

        for topic in HEAVY_TOPICS:
            t = asyncio.create_task(self._consume_topic(topic))
            self._consumer_tasks.append(t)

        logger.info(
            f"Heavy Worker 已启动，并发度={self.concurrency}, 监听 {len(HEAVY_TOPICS)} 个 topic"
        )

        try:
            await asyncio.gather(*self._consumer_tasks)
        except asyncio.CancelledError:
            logger.info("Heavy Worker 收到取消信号")

    async def _consume_topic(self, topic: str):
        queue_name = f"{topic}.queue"
        channel = self.queue._channel
        queue = None
        for _ in range(5):
            queue = await channel.get_queue(queue_name, ensure=False)
            if queue is not None:
                break
            await asyncio.sleep(1)
        if queue is None:
            logger.warning(f"队列 {queue_name} 不存在")
            return
        async with queue.iterator() as q_iter:
            async for message in q_iter:
                if not self._running:
                    break
                await self._handle_message(message)

    async def _handle_message(self, message: AbstractIncomingMessage):
        async with message.process(requeue=False):
            try:
                body = json.loads(message.body.decode("utf-8"))
            except Exception:
                return
            task_id = body.get("task_id")
            step_id = body.get("step_id")
            payload = body.get("payload", {})
            try:
                await self.orchestrator.execute_step(task_id, step_id, payload)
            except Exception as e:
                logger.error(f"heavy worker execute_step 异常: {e}")

    async def stop(self):
        self._running = False
        for t in self._consumer_tasks:
            t.cancel()
        await close_queue_client()


async def main():
    worker = HeavyWorker()
    loop = asyncio.get_event_loop()

    def _shutdown():
        logger.info("收到 SIGINT, heavy worker 停止")
        asyncio.create_task(worker.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
