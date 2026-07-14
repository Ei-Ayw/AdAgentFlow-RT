"""PostgreSQL、Redis、RabbitMQ 真实基础设施压测（不调用 LLM）。"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
import uuid
from pathlib import Path

import aio_pika

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(percent * len(ordered)) - 1)
    return ordered[index]


def summary(name: str, values: list[float], errors: int, elapsed: float) -> dict:
    return {
        "component": name,
        "operations": len(values) + errors,
        "errors": errors,
        "throughput_ops_s": round((len(values) + errors) / elapsed, 2),
        "latency_ms": {
            "p50": round(percentile(values, 0.50) * 1000, 2),
            "p95": round(percentile(values, 0.95) * 1000, 2),
            "p99": round(percentile(values, 0.99) * 1000, 2),
            "max": round(max(values, default=0) * 1000, 2),
        },
    }


async def bounded_run(count: int, concurrency: int, operation) -> tuple[list[float], int, float]:
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    errors = 0

    async def one(index: int) -> None:
        nonlocal errors
        async with semaphore:
            started = time.perf_counter()
            try:
                await operation(index)
                latencies.append(time.perf_counter() - started)
            except Exception:
                errors += 1

    started = time.perf_counter()
    await asyncio.gather(*(one(index) for index in range(count)))
    return latencies, errors, time.perf_counter() - started


async def benchmark_postgres(count: int, concurrency: int, run_id: str) -> dict:
    from app.db.database import session_scope
    from app.models.outbox import OutboxEvent

    def insert(index: int) -> None:
        with session_scope() as db:
            db.add(
                OutboxEvent(
                    event_id=uuid.uuid4().hex,
                    task_id=f"load-{run_id}-{index}",
                    step_id="benchmark",
                    payload={"index": index},
                    status="published",
                    attempts=1,
                )
            )

    async def operation(index: int) -> None:
        await asyncio.to_thread(insert, index)

    values, errors, elapsed = await bounded_run(count, concurrency, operation)
    with session_scope() as db:
        db.query(OutboxEvent).filter(
            OutboxEvent.task_id.like(f"load-{run_id}-%")
        ).delete(synchronize_session=False)
    return summary("postgres", values, errors, elapsed)


async def benchmark_redis(count: int, concurrency: int, run_id: str) -> dict:
    from app.services import idempotency

    redis = await idempotency.get_redis()

    async def operation(index: int) -> None:
        key = f"load:{run_id}:{index}"
        await redis.set(name=key, value="1", ex=60)
        await redis.get(key)
        await redis.delete(key)

    try:
        values, errors, elapsed = await bounded_run(count, concurrency, operation)
    finally:
        await redis.aclose()
        idempotency._pool = None
    return summary("redis_set_get_delete", values, errors, elapsed)


async def benchmark_rabbitmq(count: int, concurrency: int, run_id: str) -> dict:
    from app.core.config import settings

    connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    channel = await connection.channel(publisher_confirms=True)
    queue = await channel.declare_queue(
        f"adagentflow.load.{run_id}", exclusive=True, auto_delete=True
    )

    async def operation(index: int) -> None:
        await channel.default_exchange.publish(
            aio_pika.Message(body=str(index).encode(), delivery_mode=1),
            routing_key=queue.name,
        )

    try:
        values, errors, elapsed = await bounded_run(count, concurrency, operation)
    finally:
        await channel.close()
        await connection.close()
    return summary("rabbitmq_publish_confirm", values, errors, elapsed)


async def main() -> int:
    parser = argparse.ArgumentParser(description="真实基础设施压测，不调用 LLM")
    parser.add_argument("--operations", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=20)
    args = parser.parse_args()
    if args.operations < 1 or args.concurrency < 1:
        parser.error("operations 和 concurrency 必须大于 0")

    run_id = uuid.uuid4().hex[:12]
    results = [
        await benchmark_postgres(args.operations, args.concurrency, run_id),
        await benchmark_redis(args.operations, args.concurrency, run_id),
        await benchmark_rabbitmq(args.operations, args.concurrency, run_id),
    ]
    report = {
        "scope": "infrastructure-only; excludes LLM latency and quality",
        "operations_per_component": args.operations,
        "concurrency": args.concurrency,
        "results": results,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(result["errors"] == 0 for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
