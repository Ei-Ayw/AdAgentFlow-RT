"""Outbox 入库与补发服务。

交付语义为 at-least-once：若 RabbitMQ 发布成功后进程在标记 published 前退出，
事件会再次发布，消费端依靠 TaskStep 状态和执行租约保证业务结果等价一次。
"""
from __future__ import annotations

import asyncio
import datetime
import uuid
from typing import Optional

from sqlalchemy import or_
from prometheus_client import Counter, Gauge

from app.core.config import settings
from app.core.logging import get_logger
from app.db.database import session_scope
from app.models.outbox import OutboxEvent
from app.services.queue import QueueClient, get_queue_client


logger = get_logger()

OUTBOX_PUBLISH_TOTAL = Counter(
    "adagentflow_outbox_publish_total",
    "Outbox publish attempts grouped by result.",
    ["result"],
)
OUTBOX_EVENTS = Gauge(
    "adagentflow_outbox_events",
    "Current number of outbox events grouped by status.",
    ["status"],
)


def refresh_status_metrics() -> None:
    """每个补发批次刷新一次积压量，避免每条事件额外执行多次 COUNT。"""
    with session_scope() as db:
        for status in ("pending", "publishing", "failed", "published", "exhausted"):
            count = db.query(OutboxEvent).filter(OutboxEvent.status == status).count()
            OUTBOX_EVENTS.labels(status=status).set(count)


def enqueue_step_event(
    db,
    *,
    task_id: str,
    step_id: str,
    payload: dict,
    delay_seconds: int = 0,
) -> OutboxEvent:
    """在调用方业务事务中写入待发布事件。"""
    event = OutboxEvent(
        event_id=uuid.uuid4().hex,
        event_type="step.dispatch",
        task_id=task_id,
        step_id=step_id,
        payload=payload,
        delay_seconds=max(0, int(delay_seconds)),
        status="pending",
        attempts=0,
        available_at=datetime.datetime.now(datetime.timezone.utc),
    )
    db.add(event)
    return event


async def _publish(event: OutboxEvent, queue: QueueClient) -> None:
    if event.delay_seconds:
        await queue.publish_step_delayed(
            event.task_id,
            event.step_id,
            event.payload,
            delay_seconds=event.delay_seconds,
        )
    else:
        await queue.publish_step(event.task_id, event.step_id, event.payload)


def _mark_result(event_id: str, *, success: bool, error: str = "") -> None:
    with session_scope() as db:
        row = db.query(OutboxEvent).filter(OutboxEvent.event_id == event_id).first()
        if not row:
            return
        row.lock_owner = None
        row.locked_at = None
        if success:
            row.status = "published"
            row.published_at = datetime.datetime.now(datetime.timezone.utc)
            row.last_error = None
        else:
            row.status = (
                "exhausted"
                if row.attempts >= settings.outbox_max_attempts
                else "failed"
            )
            row.last_error = error[:2000]


async def try_publish_event(
    event: OutboxEvent,
    queue: Optional[QueueClient] = None,
) -> bool:
    """提交事务后立即尝试发布；失败事件由 Outbox Worker 后续补发。"""
    queue = queue or get_queue_client()
    try:
        await _publish(event, queue)
    except Exception as exc:
        OUTBOX_PUBLISH_TOTAL.labels(result="failed").inc()
        _mark_result(event.event_id, success=False, error=str(exc))
        logger.error(f"Outbox 发布失败，等待补发: event_id={event.event_id}, error={exc}")
        return False
    OUTBOX_PUBLISH_TOTAL.labels(result="published").inc()
    _mark_result(event.event_id, success=True)
    return True


def claim_pending_events(limit: int = 100) -> list[OutboxEvent]:
    """短事务认领事件；超时的 publishing 事件可被其他 Worker 接管。"""
    now = datetime.datetime.now(datetime.timezone.utc)
    stale_before = now - datetime.timedelta(seconds=settings.outbox_lock_timeout)
    owner = uuid.uuid4().hex
    with session_scope() as db:
        rows = (
            db.query(OutboxEvent)
            .filter(
                OutboxEvent.attempts < settings.outbox_max_attempts,
                OutboxEvent.available_at <= now,
                or_(
                    OutboxEvent.status.in_(["pending", "failed"]),
                    (OutboxEvent.status == "publishing")
                    & (OutboxEvent.locked_at < stale_before),
                ),
            )
            .order_by(OutboxEvent.id.asc())
            .with_for_update(skip_locked=True)
            .limit(limit)
            .all()
        )
        for row in rows:
            row.status = "publishing"
            row.lock_owner = owner
            row.locked_at = now
            row.attempts = (row.attempts or 0) + 1
        # Session 关闭后仍可读取字段，因为 expire_on_commit=False。
        return list(rows)


async def publish_pending_events(
    queue: Optional[QueueClient] = None,
    *,
    limit: int = 100,
) -> int:
    queue = queue or get_queue_client()
    rows = claim_pending_events(limit=limit)
    published = 0
    for row in rows:
        if await try_publish_event(row, queue):
            published += 1
    refresh_status_metrics()
    return published


async def run_outbox_loop(stop_event: asyncio.Event) -> None:
    queue = get_queue_client()
    while not stop_event.is_set():
        try:
            count = await publish_pending_events(queue, limit=settings.outbox_batch_size)
            if count:
                logger.info(f"Outbox 补发完成: {count} 条")
        except Exception as exc:
            logger.error(f"Outbox 扫描失败: {exc}")
        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=settings.outbox_poll_interval
            )
        except asyncio.TimeoutError:
            pass
