"""Transactional Outbox 的事务、失败保留与补发测试。"""
from __future__ import annotations

import pytest
from contextlib import contextmanager


pytestmark = pytest.mark.asyncio


@contextmanager
def real_session(sqlite_db):
    db = sqlite_db["session_local"]()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class RecordingQueue:
    def __init__(self, fail=False):
        self.fail = fail
        self.messages = []

    async def publish_step(self, task_id, step_id, payload):
        if self.fail:
            raise ConnectionError("rabbitmq unavailable")
        self.messages.append((task_id, step_id, payload, 0))

    async def publish_step_delayed(self, task_id, step_id, payload, delay_seconds):
        if self.fail:
            raise ConnectionError("rabbitmq unavailable")
        self.messages.append((task_id, step_id, payload, delay_seconds))


async def test_outbox_event_commits_and_marks_published(sqlite_db):
    from app.models.outbox import OutboxEvent
    from app.services.outbox import enqueue_step_event, try_publish_event

    with real_session(sqlite_db) as db:
        event = enqueue_step_event(
            db,
            task_id="task-1",
            step_id="script_generation",
            payload={"attempt": 1},
        )

    queue = RecordingQueue()
    assert await try_publish_event(event, queue)
    with real_session(sqlite_db) as db:
        stored = db.query(OutboxEvent).filter(OutboxEvent.event_id == event.event_id).first()
        assert stored.status == "published"
        assert stored.published_at is not None
    assert queue.messages == [
        ("task-1", "script_generation", {"attempt": 1}, 0)
    ]


async def test_outbox_rollback_does_not_leave_event(sqlite_db):
    from app.models.outbox import OutboxEvent
    from app.services.outbox import enqueue_step_event

    with pytest.raises(RuntimeError):
        with real_session(sqlite_db) as db:
            enqueue_step_event(
                db,
                task_id="task-rollback",
                step_id="product_analysis",
                payload={},
            )
            raise RuntimeError("business transaction rollback")

    with real_session(sqlite_db) as db:
        assert db.query(OutboxEvent).count() == 0


async def test_failed_event_is_recovered_by_outbox_worker(sqlite_db):
    from app.models.outbox import OutboxEvent
    from app.services.outbox import (
        enqueue_step_event,
        publish_pending_events,
        try_publish_event,
    )

    with real_session(sqlite_db) as db:
        event = enqueue_step_event(
            db,
            task_id="task-recover",
            step_id="storyboard_planning",
            payload={"attempt": 2},
            delay_seconds=5,
        )

    assert not await try_publish_event(event, RecordingQueue(fail=True))
    with real_session(sqlite_db) as db:
        failed = db.query(OutboxEvent).filter(OutboxEvent.event_id == event.event_id).first()
        assert failed.status == "failed"

    recovered_queue = RecordingQueue()
    assert await publish_pending_events(recovered_queue) == 1
    assert recovered_queue.messages == [
        ("task-recover", "storyboard_planning", {"attempt": 2}, 5)
    ]
    with real_session(sqlite_db) as db:
        recovered = db.query(OutboxEvent).filter(OutboxEvent.event_id == event.event_id).first()
        assert recovered.status == "published"
        assert recovered.attempts == 1


async def test_outbox_marks_event_exhausted_after_max_attempts(
    sqlite_db, monkeypatch
):
    from app.core.config import settings
    from app.models.outbox import OutboxEvent
    from app.services.outbox import enqueue_step_event, publish_pending_events

    monkeypatch.setattr(settings, "outbox_max_attempts", 1)
    with real_session(sqlite_db) as db:
        event = enqueue_step_event(
            db,
            task_id="task-exhausted",
            step_id="material_suggestion",
            payload={"attempt": 1},
        )

    assert await publish_pending_events(RecordingQueue(fail=True)) == 0
    with real_session(sqlite_db) as db:
        stored = (
            db.query(OutboxEvent)
            .filter(OutboxEvent.event_id == event.event_id)
            .first()
        )
        assert stored.status == "exhausted"
        assert stored.attempts == 1
        assert "rabbitmq unavailable" in stored.last_error

    assert await publish_pending_events(RecordingQueue()) == 0
