"""真实进程级故障注入。

要求先启动 integration compose 并执行 Alembic。脚本会让子进程在关键窗口
SIGKILL，随后验证 Redis 租约和 Transactional Outbox 是否自动恢复。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _kill_self() -> None:
    sys.stdout.flush()
    os.kill(os.getpid(), signal.SIGKILL)


async def _child_lock() -> None:
    from app.services.idempotency import acquire_idempotent

    task_id = os.environ["FAULT_TASK_ID"]
    owner = await acquire_idempotent(task_id, "product_analysis", ttl=2)
    print(f"FAULT_LOCK_OWNER={owner}", flush=True)
    _kill_self()


def _child_outbox() -> None:
    from app.db.database import session_scope
    from app.services.outbox import enqueue_step_event

    task_id = os.environ["FAULT_TASK_ID"]
    with session_scope() as db:
        event = enqueue_step_event(
            db,
            task_id=task_id,
            step_id="product_analysis",
            payload={"fault_injection": True},
        )
    print(f"FAULT_EVENT_ID={event.event_id}", flush=True)
    _kill_self()


def _run_child(mode: str, task_id: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["FAULT_TASK_ID"] = task_id
    env["PYTHONUNBUFFERED"] = "1"
    return subprocess.run(
        [sys.executable, __file__, f"--child-{mode}"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


async def run_lock_scenario() -> dict:
    from app.services import idempotency

    task_id = f"fault-lock-{uuid.uuid4().hex}"
    child = _run_child("lock", task_id)
    redis = await idempotency.get_redis()
    key = idempotency.idempotent_key(task_id, "product_analysis")
    existed_after_kill = bool(await redis.exists(key))
    deadline = time.monotonic() + 5
    while await redis.exists(key) and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
    recovered = not bool(await redis.exists(key))
    await redis.aclose()
    idempotency._pool = None
    return {
        "scenario": "redis_lock_owner_process_sigkill",
        "child_returncode": child.returncode,
        "lock_existed_after_kill": existed_after_kill,
        "recovered": recovered,
    }


async def run_outbox_scenario() -> dict:
    from app.db.database import session_scope
    from app.models.outbox import OutboxEvent
    from app.services.outbox import publish_pending_events
    from app.services.queue import QueueClient

    task_id = f"fault-outbox-{uuid.uuid4().hex}"
    child = _run_child("outbox", task_id)
    with session_scope() as db:
        row = db.query(OutboxEvent).filter(OutboxEvent.task_id == task_id).first()
        committed_after_kill = row is not None and row.status == "pending"
        event_id = row.event_id if row else None

    queue = QueueClient()
    try:
        published_count = await publish_pending_events(queue, limit=100)
    finally:
        await queue.close()

    with session_scope() as db:
        row = db.query(OutboxEvent).filter(OutboxEvent.event_id == event_id).first()
        recovered = row is not None and row.status == "published"
    return {
        "scenario": "db_commit_before_publish_process_sigkill",
        "child_returncode": child.returncode,
        "event_committed_after_kill": committed_after_kill,
        "published_in_batch": published_count,
        "recovered": recovered,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description="AdAgentFlow 真实进程故障注入")
    parser.add_argument("--child-lock", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--child-outbox", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.child_lock:
        await _child_lock()
        return 137
    if args.child_outbox:
        _child_outbox()
        return 137

    results = [await run_lock_scenario(), await run_outbox_scenario()]
    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    return 0 if all(result["recovered"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
