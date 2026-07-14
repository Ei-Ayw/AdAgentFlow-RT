"""真实 PostgreSQL、Redis、RabbitMQ 集成测试。

默认跳过。运行方式：

RUN_INFRA_TESTS=1 \
DATABASE_URL=postgresql://... \
REDIS_URL=redis://... \
RABBITMQ_URL=amqp://... \
pytest tests/test_infrastructure_integration.py -q
"""
from __future__ import annotations

import os
import uuid

import aio_pika
import psycopg2
import pytest
import redis.asyncio as redis_async


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INFRA_TESTS") != "1",
        reason="set RUN_INFRA_TESTS=1 to run real infrastructure tests",
    ),
]


def test_real_postgres_roundtrip():
    connection = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            assert cursor.fetchone() == (1,)
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_real_redis_setnx_and_expiry():
    client = redis_async.from_url(os.environ["REDIS_URL"], decode_responses=True)
    key = f"integration:{uuid.uuid4().hex}"
    try:
        assert await client.set(key, "owner", nx=True, ex=10)
        assert not await client.set(key, "other", nx=True, ex=10)
        assert await client.get(key) == "owner"
    finally:
        await client.delete(key)
        await client.aclose()


@pytest.mark.asyncio
async def test_real_rabbitmq_publish_and_consume():
    connection = await aio_pika.connect_robust(os.environ["RABBITMQ_URL"])
    queue_name = f"integration.{uuid.uuid4().hex}"
    try:
        channel = await connection.channel()
        queue = await channel.declare_queue(queue_name, auto_delete=True)
        await channel.default_exchange.publish(
            aio_pika.Message(
                body=b"adagentflow-integration",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=queue_name,
        )
        message = await queue.get(timeout=5)
        assert message.body == b"adagentflow-integration"
        await message.ack()
    finally:
        await connection.close()


class FailingQueue:
    async def publish_step(self, task_id, step_id, payload):
        raise ConnectionError("simulated broker outage")

    async def publish_step_delayed(self, task_id, step_id, payload, delay_seconds):
        raise ConnectionError("simulated broker outage")


@pytest.mark.asyncio
async def test_real_outbox_failure_and_recovery():
    from app.db.database import session_scope
    from app.models.outbox import OutboxEvent
    from app.services.outbox import (
        enqueue_step_event,
        publish_pending_events,
        try_publish_event,
    )
    from app.services.queue import QueueClient

    task_id = f"integration-{uuid.uuid4().hex}"
    with session_scope() as db:
        event = enqueue_step_event(
            db,
            task_id=task_id,
            step_id="product_analysis",
            payload={"integration": True},
        )

    assert not await try_publish_event(event, FailingQueue())
    with session_scope() as db:
        stored = db.query(OutboxEvent).filter(OutboxEvent.event_id == event.event_id).first()
        assert stored.status == "failed"

    queue = QueueClient(os.environ["RABBITMQ_URL"])
    try:
        assert await publish_pending_events(queue) >= 1
    finally:
        await queue.close()

    with session_scope() as db:
        stored = db.query(OutboxEvent).filter(OutboxEvent.event_id == event.event_id).first()
        assert stored.status == "published"
