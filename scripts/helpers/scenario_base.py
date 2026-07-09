"""场景基类 - 提供通用 worker pool 模拟 / 任务驱动

真实部署里：
- API 收到任务 → 写入 RabbitMQ
- Worker pool 拉取消息 → 调用 orchestrator.execute_step

压测里我们直接：
- 异步并发调用 orchestrator.execute_step
- 模拟 worker pool 的并发度
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from tqdm import tqdm

from app.services.orchestrator import get_orchestrator

from scripts.helpers.mock_infra import get_context
from scripts.helpers.metrics_collector import MetricsCollector, TaskMetric


@dataclass
class ScenarioConfig:
    concurrency: int = 50
    duration: int = 30
    bad_json_rate: float = 0.0
    timeout_rate: float = 0.0
    crash_at: int = 50
    replication: int = 2
    judge_pass_rate: float = 1.0
    seed: int = 42


def make_product(i: int) -> Dict[str, Any]:
    """生成一条测试商品输入"""
    products = [
        ("Portable Neck Fan", "commuters"),
        ("Smart LED Desk Lamp", "remote workers"),
        ("Wireless Earbuds Pro", "fitness enthusiasts"),
        ("Insulated Tumbler", "outdoor hikers"),
        ("Foldable Travel Bag", "business travelers"),
        ("Aromatherapy Diffuser", "home wellness"),
        ("Magnetic Phone Mount", "drivers"),
        ("Mini Air Purifier", "urban dwellers"),
        ("Bamboo Cutting Board", "home cooks"),
        ("Smart Water Bottle", "athletes"),
    ]
    name, user = products[i % len(products)]
    return {
        "product_name": f"{name} #{i}",
        "target_user": user,
        "selling_points": [
            "long battery life",
            "lightweight design",
            "premium quality",
        ],
        "platform": "TikTok",
        "style": "dramatic before-after ad",
        "duration": 15,
    }


async def run_single_task(
    metric: TaskMetric,
    task_id: str,
    payload: Dict[str, Any],
    collector: MetricsCollector,
) -> None:
    """驱动一个完整 task 走完 5 个 step

    不依赖真实 RabbitMQ / Worker，直接调用 orchestrator.execute_step。
    注意：幂等拦截由 orchestrator.execute_step 内部负责，
    这里不要在外层再 acquire，避免被自己拦截。
    """
    from app.core.state_machine import WORKFLOW_STEPS, next_step_or_done
    from app.core.failure_codes import FailureReason

    ctx = get_context()

    current_step = WORKFLOW_STEPS[0]
    attempt = 1
    history: Dict[str, Any] = {}
    failure_feedback = ""

    while current_step is not None:
        step_start = time.time()
        existing = ctx.db.get_step(task_id, current_step)
        if existing is None:
            from scripts.helpers.mock_infra import MockStep
            from app.core.state_machine import STEP_NAME_DISPLAY
            ctx.db.add_step(MockStep(task_id, current_step,
                                     STEP_NAME_DISPLAY.get(current_step, current_step)))
            existing = ctx.db.get_step(task_id, current_step)
        existing.status = "running"
        existing.started_at = step_start
        existing.retry_count += 1

        orchestrator = get_orchestrator()
        step_payload = {
            "task_id": task_id,
            "trace_id": payload.get("trace_id", ""),
            "product": payload.get("product", {}),
            "history": history,
            "attempt": attempt,
            "failure_feedback": failure_feedback,
        }
        try:
            await orchestrator.execute_step(task_id, current_step, step_payload)
        except Exception as e:
            existing.status = "failed"
            existing.error_message = str(e)
            existing.finished_at = time.time()

        step = ctx.db.get_step(task_id, current_step)
        if step is None:
            break

        json_failed = (step.failure_reason in (
            FailureReason.JSON_PARSE_ERROR.value,
            FailureReason.SCHEMA_VALIDATION_ERROR.value,
        ))
        collector.record_step(
            metric, current_step,
            step.status == "success",
            step.latency_ms or int((time.time() - step_start) * 1000),
            step.retry_count,
            json_failed=json_failed,
        )

        if step.status == "success":
            history[current_step] = step.output_payload
            failure_feedback = ""
            attempt = 1
            current_step = next_step_or_done(current_step)
        elif step.status == "dead_letter" or step.failure_reason == FailureReason.DEAD_LETTER.value:
            metric.went_to_dead_letter = True
            break
        else:
            metric.json_failure_count += 1
            attempt += 1
            failure_feedback = (
                f"reason={step.failure_reason}, error={step.error_message}"
            )
            if attempt > 3:
                metric.went_to_dead_letter = True
                ctx.db.tasks[task_id].status = "dead_letter"
                break
            continue

    t = ctx.db.tasks.get(task_id)
    final_status = t.status if t else "unknown"
    metric.finished_at = time.time()
    metric.success = (final_status == "success")
    metric.final_status = final_status
    metric.retry_count = t.retry_count if t else 0


async def run_concurrent(
    config: ScenarioConfig,
    collector: MetricsCollector,
    task_count: Optional[int] = None,
    bar_desc: str = "压测进度",
) -> None:
    """并发跑 N 个 task，使用信号量控制并发度"""
    from app.services.tracing import generate_task_id, generate_trace_id

    n = task_count or config.concurrency
    sem = asyncio.Semaphore(config.concurrency)
    ctx = get_context()

    pbar = tqdm(total=n, desc=bar_desc, ncols=80)

    async def _one(i: int):
        task_id = generate_task_id()
        trace_id = generate_trace_id()
        product = make_product(i)
        # 在 mock DB 里先建 task 占位
        from scripts.helpers.mock_infra import MockTask
        ctx.db.add_task(MockTask(task_id=task_id, trace_id=trace_id,
                                 status="created", product=product))
        metric = collector.new_task(task_id)
        async with sem:
            await run_single_task(
                metric, task_id,
                {"trace_id": trace_id, "product": product},
                collector,
            )
        pbar.update(1)

    tasks = [asyncio.create_task(_one(i)) for i in range(n)]
    await asyncio.gather(*tasks, return_exceptions=True)
    pbar.close()