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

# worker 监听的 topic 列表
HEAVY_TOPICS = [
    "ad_task.repair",
    "ad_task.image_generation",
    "ad_task.video_generation",
    "ad_task.composition",
]


class HeavyWorker:
    """
    初始化一个 worker 实例。
    1. get_queue_client() 拿到 RabbitMQ 客户端单例。
    2. get_orchestrator() 拿到工作流编排器单例。
    3. WORKER_CONCURRENCY 控制 worker 并发，默认 2。
    4. _running 是停止开关。
    5. _consumer_tasks 保存每个 topic 对应的消费协程。
    """
    def __init__(self):
        self.queue = get_queue_client()
        self.orchestrator = get_orchestrator()
        self.concurrency = int(__import__("os").environ.get("WORKER_CONCURRENCY", "2"))
        db_capacity = settings.db_pool_size + settings.db_max_overflow
        if self.concurrency < 1 or self.concurrency > db_capacity:
            raise ValueError(
                f"WORKER_CONCURRENCY={self.concurrency} 必须在 1..{db_capacity}，"
                "避免同步 ORM 耗尽连接池"
            )
        self._running = False
        self._consumer_tasks: List[asyncio.Task] = []
        self._inflight: set[asyncio.Task] = set()
        self._slots = asyncio.Semaphore(self.concurrency)

    async def run(self):
        # 连接 RabbitMQ
        await self.queue.connect()
        # 开始工作
        self._running = True
        channel = self.queue._channel
        # 控制 broker 一次发多少未 ack 消息给这个 consumer，防止一次压太多任务
        await channel.set_qos(prefetch_count=self.concurrency * 2)

        for topic in HEAVY_TOPICS:
            # 每个 topic 启一个独立消费任务
            t = asyncio.create_task(self._consume_topic(topic))
            self._consumer_tasks.append(t)

        logger.info(
            f"Heavy Worker 已启动，并发度={self.concurrency}, 监听 {len(HEAVY_TOPICS)} 个 topic"
        )

        try:
            # 多个 topic，并行消费，把多个异步任务同时跑，等它们都结束后再返回
            # *self._consumer_tasks 是解包，会变成：task1, task2, task3
            await asyncio.gather(*self._consumer_tasks)
        except asyncio.CancelledError:
            logger.info("Heavy Worker 收到取消信号")

    """
    等待所有 consumer 任务结束
    正常情况下它会一直挂着，直到被取消或发生异常
    """
    async def _consume_topic(self, topic: str):
        # 把 topic 名转成队列名，比如 ad_task.repair.queue
        queue_name = f"{topic}.queue"
        channel = self.queue._channel
        queue = None
        for _ in range(5):
            # 最多等 5 次，每次 1 秒，尝试拿队列
            # ensure=False 表示这里只是查有没有，不主动创建。
            queue = await channel.get_queue(queue_name, ensure=False)
            if queue is not None:
                break
            await asyncio.sleep(1)
        if queue is None:
            logger.warning(f"队列 {queue_name} 不存在")
            return
        # 监听队列，异步迭代消息，用队列迭代器持续消费消息
        async with queue.iterator() as q_iter:
            async for message in q_iter:
                if not self._running:
                    break
                # 用队列迭代器持续消费消息
                task = asyncio.create_task(self._run_limited(message))
                self._inflight.add(task)
                task.add_done_callback(self._inflight.discard)

    async def _run_limited(self, message: AbstractIncomingMessage):
        async with self._slots:
            await self._handle_message(message)

    """
    消息处理上下文。
    1、正常结束会 ack。
    2、如果上下文里抛异常，requeue=False 表示不要重新入队，通常会被拒绝或进入死信链路，取决于队列配置。
    """
    async def _handle_message(self, message: AbstractIncomingMessage):
        try:
            body = json.loads(message.body.decode("utf-8"))
        except Exception as e:
            logger.error(f"heavy worker 消息解析失败: {e}")
            await message.reject(requeue=False)
            return

        try:
            async with message.process(requeue=True, reject_on_redelivered=True):
                task_id = body.get("task_id")
                step_id = body.get("step_id")
                payload = body.get("payload", {})
                with logger.contextualize(
                    task_id=task_id,
                    step_id=step_id,
                    message_id=getattr(message, "message_id", None),
                    trace_id=payload.get("trace_id"),
                ):
                    await self.orchestrator.execute_step(task_id, step_id, payload)
        except Exception as e:
            logger.error(f"heavy worker 执行异常，消息已按投递状态处理: {e}")

    async def stop(self):
        self._running = False
        for t in self._consumer_tasks:
            t.cancel()
        if self._consumer_tasks:
            await asyncio.gather(*self._consumer_tasks, return_exceptions=True)
        if self._inflight:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._inflight, return_exceptions=True),
                    timeout=settings.worker_shutdown_timeout,
                )
            except asyncio.TimeoutError:
                logger.warning("优雅停机超时，未完成消息将由 RabbitMQ 重新投递")
                for task in self._inflight:
                    task.cancel()
        await close_queue_client()


async def main():
    worker = HeavyWorker()
    # 拿当前事件循环
    loop = asyncio.get_event_loop()

    def _shutdown():
        logger.info("收到 SIGINT, heavy worker 停止")
        asyncio.create_task(worker.stop())

    # 收到退出信号时，异步触发停止流程
    for sig in (signal.SIGINT, signal.SIGTERM):
        # 给 Ctrl+C 和终止信号挂上处理器。
        # 某些平台不支持 signal handler，所以捕获 NotImplementedError
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass
    # 启动主消费逻辑
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
