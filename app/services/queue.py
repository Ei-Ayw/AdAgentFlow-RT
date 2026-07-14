"""队列配置 + 生产者

Topic 结构:
  ad_task.created       - 新任务入口
  ad_task.{step_id}     - 每个 step 一条
  ad_task.dead_letter   - 死信
"""
import json
import asyncio
import uuid
from typing import Any, Dict, Optional

import aio_pika
from aio_pika.abc import (
    AbstractRobustConnection,
    AbstractRobustChannel,
    AbstractExchange,
    AbstractQueue,
    AbstractMessage,
)

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger()

EXCHANGE_NAME = "adagentflow.tasks"
DLX_NAME = "adagentflow.dlx"

# Topic routing key
TOPIC_CREATED = "ad_task.created"
TOPIC_DEAD_LETTER = "ad_task.dead_letter"

WORKFLOW_TOPICS = [
    "ad_task.product_analysis",
    "ad_task.script_generation",
    "ad_task.storyboard_planning",
    "ad_task.material_suggestion",
    "ad_task.quality_evaluation",
    "ad_task.repair",
]


class QueueClient:
    """异步 RabbitMQ 客户端 - 生产者与消费者共用"""

    def __init__(self, url: Optional[str] = None):
        self.url = url or settings.rabbitmq_url
        self._connection: Optional[AbstractRobustConnection] = None
        self._channel: Optional[AbstractRobustChannel] = None
        self._exchange: Optional[AbstractExchange] = None
        self._dlx: Optional[AbstractExchange] = None

    async def connect(self):
        if self._connection is not None and not self._connection.is_closed:
            return
        self._connection = await aio_pika.connect_robust(self.url, timeout=20)
        self._channel = await self._connection.channel()
        await self._channel.set_qos(prefetch_count=settings.rabbitmq_prefetch)

        # Topic exchange
        self._exchange = await self._channel.declare_exchange(
            EXCHANGE_NAME,
            type=aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        # DLX
        self._dlx = await self._channel.declare_exchange(
            DLX_NAME,
            type=aio_pika.ExchangeType.TOPIC,
            durable=True,
        )

        # 死信队列
        dlq = await self._channel.declare_queue("ad_task.dead_letter.queue", durable=True)
        await dlq.bind(self._dlx, routing_key="ad_task.dead_letter")

        # 工作队列 - 每个 step 一条
        for topic in WORKFLOW_TOPICS:
            queue_name = f"{topic}.queue"
            q = await self._channel.declare_queue(
                queue_name,
                durable=True,
                arguments={
                    "x-dead-letter-exchange": DLX_NAME,
                    "x-dead-letter-routing-key": "ad_task.dead_letter",
                },
            )
            await q.bind(self._exchange, routing_key=topic)

        # 新任务入口
        created_q = await self._channel.declare_queue(
            "ad_task.created.queue",
            durable=True,
        )
        await created_q.bind(self._exchange, routing_key=TOPIC_CREATED)
        logger.info("RabbitMQ 连接已建立，所有队列已声明")

    async def close(self):
        if self._connection and not self._connection.is_closed:
            await self._connection.close()

    async def publish(self, routing_key: str, body: Dict[str, Any]):
        """发送消息到指定 topic"""
        await self.connect()
        msg_body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        msg = aio_pika.Message(
            body=msg_body,
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=str(uuid.uuid4()),
            headers={
                "task_id": body.get("task_id", ""),
                "step_id": body.get("step_id", ""),
            },
        )
        await self._exchange.publish(msg, routing_key=routing_key)
        logger.info(f"已发布消息 → {routing_key}: {body.get('task_id')}")

    def _step_body(self, task_id: str, step_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "task_id": task_id,
            "step_id": step_id,
            "payload": payload,
            "ts": asyncio.get_event_loop().time(),
        }

    async def publish_step(self, task_id: str, step_id: str, payload: Dict[str, Any]):
        """发布 step 任务"""
        body = self._step_body(task_id, step_id, payload)
        routing_key = f"ad_task.{step_id}"
        await self.publish(routing_key, body)

    async def publish_step_delayed(
        self,
        task_id: str,
        step_id: str,
        payload: Dict[str, Any],
        delay_seconds: int,
    ) -> None:
        """通过 RabbitMQ TTL + DLX 持久化延迟重试，不依赖 Worker 进程内 sleep。"""
        if delay_seconds <= 0:
            await self.publish_step(task_id, step_id, payload)
            return

        await self.connect()
        routing_key = f"ad_task.{step_id}"
        delay_ms = int(delay_seconds * 1000)
        queue_name = f"{routing_key}.retry.{delay_ms}.queue"
        await self._channel.declare_queue(
            queue_name,
            durable=True,
            arguments={
                "x-message-ttl": delay_ms,
                "x-dead-letter-exchange": EXCHANGE_NAME,
                "x-dead-letter-routing-key": routing_key,
            },
        )
        body = self._step_body(task_id, step_id, payload)
        message = aio_pika.Message(
            body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=str(uuid.uuid4()),
            headers={"task_id": task_id, "step_id": step_id, "retry_delay": delay_seconds},
        )
        await self._channel.default_exchange.publish(message, routing_key=queue_name)
        logger.info(f"已持久化延迟重试 → {routing_key}: {task_id}, delay={delay_seconds}s")

    async def publish_dead_letter(self, task_id: str, step_id: str, payload: Dict[str, Any]):
        await self.connect()
        body = {
            "task_id": task_id,
            "step_id": step_id,
            "payload": payload,
        }
        message = aio_pika.Message(
            body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=str(uuid.uuid4()),
            headers={"task_id": task_id, "step_id": step_id},
        )
        await self._dlx.publish(message, routing_key=TOPIC_DEAD_LETTER)


# 单例
_client_instance: Optional[QueueClient] = None


def get_queue_client() -> QueueClient:
    global _client_instance
    if _client_instance is None:
        _client_instance = QueueClient()
    return _client_instance


async def close_queue_client():
    global _client_instance
    if _client_instance is not None:
        await _client_instance.close()
        _client_instance = None
