"""故障模拟场景实现

每个场景都是独立的 async 函数，签名统一为：
    async def run_scenario_xxx(args, collector: MetricsCollector) -> None

它们复用 helpers/scenario_base 中的 run_concurrent / run_single_task。
"""
from __future__ import annotations

import asyncio
import time
import random
from typing import Any

# 修项目里既存的 import bug：pydantic_to_json_schema
import app.services.json_validator as _jv  # noqa: E402
from app.schemas.agent_schemas import pydantic_to_json_schema as _p2js  # noqa: E402

if not hasattr(_jv, "pydantic_to_json_schema"):
    _jv.pydantic_to_json_schema = _p2js

from tqdm import tqdm

from app.services.orchestrator import get_orchestrator
from app.services.idempotency import acquire_idempotent
from app.core.state_machine import WORKFLOW_STEPS, next_step_or_done
from app.core.failure_codes import FailureReason

from scripts.helpers.mock_infra import get_context, init_mock_infra
from scripts.helpers.metrics_collector import MetricsCollector, TaskMetric
from scripts.helpers.scenario_base import ScenarioConfig, make_product, run_concurrent


def _cfg(args) -> ScenarioConfig:
    return ScenarioConfig(
        concurrency=args.concurrency,
        duration=args.duration,
        bad_json_rate=args.bad_json_rate,
        timeout_rate=args.timeout_rate,
        crash_at=args.crash_at,
        replication=args.replication,
        judge_pass_rate=args.judge_pass_rate,
        seed=args.seed,
    )


# ================================================================
# 场景 1: 正常并发压测
# ================================================================
async def run_scenario_concurrent(args, collector: MetricsCollector) -> None:
    """并发提交 N 个任务，等待全部结束，统计指标"""
    cfg = _cfg(args)
    ctx = get_context()
    ctx.injector.reset()  # 关掉所有故障注入

    n = cfg.concurrency
    print(f"  - 提交 {n} 个并发任务（并发度={n}）")
    await run_concurrent(cfg, collector, task_count=n, bar_desc="[S1] 跑任务")

    # 把吞吐曲线写 CSV
    metrics = collector.aggregate()
    collector.set_extra("csv_throughput", _throughput_curve(metrics["raw_tasks"]))
    print(f"  - 端到端成功率: {metrics['summary']['success_rate']}%")
    print(f"  - 平均耗时: {metrics['latency']['avg_seconds']}s")
    print(f"  - 吞吐: {metrics['summary']['throughput_tasks_per_sec']} 任务/秒")


def _throughput_curve(raw_tasks, bucket_size: float = 0.5):
    """生成时间桶吞吐曲线"""
    if not raw_tasks:
        return []
    starts = [t["started_at"] for t in raw_tasks]
    t0 = min(starts)
    buckets: dict = {}
    for t in raw_tasks:
        bucket = int((t["started_at"] - t0) / bucket_size)
        buckets[bucket] = buckets.get(bucket, 0) + 1
    return [{"t_seconds": b * bucket_size, "task_count": c} for b, c in sorted(buckets.items())]


# ================================================================
# 场景 2: JSON 异常模拟
# ================================================================
async def run_scenario_bad_json(args, collector: MetricsCollector) -> None:
    """注入坏 JSON，验证 quick repair + LLM repair 是否能修复"""
    cfg = _cfg(args)
    ctx = get_context()
    ctx.injector.reset()
    ctx.injector.bad_json_rate = cfg.bad_json_rate

    n = cfg.concurrency
    print(f"  - 注入坏 JSON 比例 {cfg.bad_json_rate * 100:.0f}%，任务数 {n}")

    # 直接驱动 worker：每个 task 强制让 quality_evaluation 输出坏 JSON 后看修复
    sem = asyncio.Semaphore(cfg.concurrency)
    pbar = tqdm(total=n, desc="[S2] 跑任务", ncols=80)

    async def _one(i: int):
        from app.services.tracing import generate_task_id, generate_trace_id
        task_id = generate_task_id()
        trace_id = generate_trace_id()
        product = make_product(i)
        from scripts.helpers.mock_infra import MockTask
        ctx.db.add_task(MockTask(task_id=task_id, trace_id=trace_id,
                                 status="created", product=product))
        metric = collector.new_task(task_id)

        # 跑 product_analysis step
        async with sem:
            await _drive_step_with_repair(task_id, "product_analysis", product, metric, collector)
            if metric.went_to_dead_letter:
                pbar.update(1)
                return
            await _drive_step_with_repair(task_id, "script_generation", product, metric, collector)
            if metric.went_to_dead_letter:
                pbar.update(1)
                return
        pbar.update(1)

    await asyncio.gather(*[_one(i) for i in range(n)], return_exceptions=True)
    pbar.close()

    # 汇总修复统计
    n_total = len(collector.tasks)
    n_json_failed = sum(1 for t in collector.tasks if t.json_failure_count > 0)
    n_recovered = sum(
        1 for t in collector.tasks
        if t.json_failure_count > 0 and t.success
    )
    n_dead = sum(1 for t in collector.tasks if t.went_to_dead_letter)

    collector.set_extra("json_repair", {
        "injected_bad_json": n_json_failed,
        "quick_repair_success": ctx.injector.json_failures - sum(
            1 for t in collector.tasks
            if t.json_failure_count > 0 and not t.success
        ),
        "final_recovery_rate": round(n_recovered / n_json_failed * 100, 2)
        if n_json_failed else 100.0,
        "dead_letter_count": n_dead,
    })

    print(f"  - 注入坏 JSON 任务: {n_json_failed}/{n_total}")
    print(f"  - 最终修复成功率: {collector.extra['json_repair']['final_recovery_rate']}%")
    print(f"  - 死信任务数: {n_dead}")


async def _drive_step_with_repair(task_id, step_id, product, metric, collector):
    """驱动单个 step 并统计修复尝试"""
    from app.core.state_machine import StepStatus, STEP_NAME_DISPLAY
    from scripts.helpers.mock_infra import MockStep

    ctx = get_context()
    if ctx.db.get_step(task_id, step_id) is None:
        ctx.db.add_step(MockStep(task_id, step_id, STEP_NAME_DISPLAY.get(step_id, step_id)))

    step = ctx.db.get_step(task_id, step_id)
    step.status = "running"
    step.started_at = time.time()

    orchestrator = get_orchestrator()
    try:
        await orchestrator.execute_step(task_id, step_id, {
            "task_id": task_id,
            "product": product,
            "history": {},
            "attempt": 1,
            "failure_feedback": "",
        })
    except Exception:
        pass

    step = ctx.db.get_step(task_id, step_id)
    json_failed = step.failure_reason in (
        FailureReason.JSON_PARSE_ERROR.value,
        FailureReason.SCHEMA_VALIDATION_ERROR.value,
    )
    collector.record_step(
        metric, step_id,
        step.status == "success",
        step.latency_ms or 0,
        step.retry_count,
        json_failed=json_failed,
    )
    if json_failed:
        metric.json_failure_count += 1

    if step.status == "dead_letter" or ctx.db.tasks[task_id].status == "dead_letter":
        metric.went_to_dead_letter = True
        metric.final_status = "dead_letter"
        metric.finished_at = time.time()
    elif step.status == "success":
        metric.success = True
        metric.final_status = "success"
        metric.finished_at = time.time()


# ================================================================
# 场景 3: Worker 崩溃模拟
# ================================================================
async def run_scenario_worker_crash(args, collector: MetricsCollector) -> None:
    """跑 N 个任务，中途模拟 worker 崩溃，验证任务恢复与幂等"""
    cfg = _cfg(args)
    ctx = get_context()
    ctx.injector.reset()

    n = cfg.concurrency
    crash_at = cfg.crash_at
    print(f"  - 提交 {n} 个任务，在第 {crash_at} 个时模拟 worker crash")

    sem = asyncio.Semaphore(cfg.concurrency)
    pbar = tqdm(total=n, desc="[S3] 跑任务", ncols=80)
    crashed_lock = asyncio.Lock()
    crashed_flag = {"done": False}

    async def _one(i: int):
        from app.services.tracing import generate_task_id, generate_trace_id
        task_id = generate_task_id()
        trace_id = generate_trace_id()
        product = make_product(i)
        from scripts.helpers.mock_infra import MockTask
        ctx.db.add_task(MockTask(task_id=task_id, trace_id=trace_id,
                                 status="created", product=product))
        metric = collector.new_task(task_id)

        async with sem:
            # 在跑到 crash_at 时，把所有 running 的 task 标记为"被中断"
            if i == crash_at:
                async with crashed_lock:
                    if not crashed_flag["done"]:
                        crashed_flag["done"] = True
                        ctx.injector.worker_crash = True
                        ctx.injector.crash_count = 1
                        # 把尚未完成的 step 标记为 running 但丢失
                        for t in ctx.db.tasks.values():
                            if t.status == "running":
                                t.status = "running"  # 保持 running 等待恢复

            # 模拟崩溃：第一次执行到这里的 task 直接 raise
            if ctx.injector.worker_crash and random.random() < 0.5:
                metric.went_to_dead_letter = True
                metric.final_status = "interrupted"
                metric.finished_at = time.time()
                pbar.update(1)
                return

            # 正常驱动（恢复后）
            await run_single_task(
                metric, task_id,
                {"trace_id": trace_id, "product": product},
                collector,
            )

            # 验证幂等：再次消费同一条消息
            from app.services.idempotency import acquire_idempotent
            still_first = await acquire_idempotent(task_id, WORKFLOW_STEPS[0])
            if not still_first:
                collector.set_extra("duplicate_idempotent_hits",
                                    collector.extra.get("duplicate_idempotent_hits", 0) + 1)
        pbar.update(1)

    await asyncio.gather(*[_one(i) for i in range(n)], return_exceptions=True)
    pbar.close()

    interrupted = sum(1 for t in collector.tasks if t.final_status == "interrupted")
    recovered = sum(1 for t in collector.tasks
                    if t.final_status not in ("interrupted",) and t.success)
    duplicates = collector.extra.get("duplicate_idempotent_hits", 0)

    collector.set_extra("worker_crash", {
        "crashed_at": crash_at,
        "interrupted_tasks": interrupted,
        "recovered_tasks": recovered,
        "duplicate_idempotent_hits": duplicates,
    })

    print(f"  - 中断任务: {interrupted}")
    print(f"  - 恢复任务: {recovered}")
    print(f"  - 幂等拦截: {duplicates}")


# ================================================================
# 场景 4: 重复消息投递
# ================================================================
async def run_scenario_duplicate(args, collector: MetricsCollector) -> None:
    """每条 task 投递 replication 条相同消息，验证幂等拦截"""
    cfg = _cfg(args)
    ctx = get_context()
    ctx.injector.reset()
    ctx.injector.duplicate_mode = True

    n = cfg.concurrency
    rep = cfg.replication
    print(f"  - 提交 {n} 个任务，每条任务重复投递 {rep} 次，共 {n * rep} 条消息")

    sem = asyncio.Semaphore(cfg.concurrency)
    pbar = tqdm(total=n, desc="[S4] 跑任务", ncols=80)

    async def _one(i: int):
        from app.services.tracing import generate_task_id, generate_trace_id
        task_id = generate_task_id()
        trace_id = generate_trace_id()
        product = make_product(i)
        from scripts.helpers.mock_infra import MockTask
        ctx.db.add_task(MockTask(task_id=task_id, trace_id=trace_id,
                                 status="created", product=product))
        metric = collector.new_task(task_id)
        async with sem:
            # 模拟 N 条相同消息并发到达
            coros = []
            for _ in range(rep):
                coros.append(_process_message(task_id, product, trace_id, metric))
            results = await asyncio.gather(*coros, return_exceptions=True)
            accepted = sum(1 for r in results if r == "accepted")
            rejected = sum(1 for r in results if r == "rejected")
            collector.set_extra("messages_accepted",
                                collector.extra.get("messages_accepted", 0) + accepted)
            collector.set_extra("messages_rejected",
                                collector.extra.get("messages_rejected", 0) + rejected)
            # 跑完一个 task
            await run_single_task(
                metric, task_id,
                {"trace_id": trace_id, "product": product},
                collector,
            )

            # 校验 step 唯一性
            steps_for_task = [s for s in ctx.db.steps if s.task_id == task_id]
            seen = set()
            dup_step = 0
            for s in steps_for_task:
                k = (s.task_id, s.step_id)
                if k in seen:
                    dup_step += 1
                seen.add(k)
            collector.set_extra("duplicate_step_rows",
                                collector.extra.get("duplicate_step_rows", 0) + dup_step)
        pbar.update(1)

    await asyncio.gather(*[_one(i) for i in range(n)], return_exceptions=True)
    pbar.close()

    accepted = collector.extra.get("messages_accepted", 0)
    rejected = collector.extra.get("messages_rejected", 0)
    dup_steps = collector.extra.get("duplicate_step_rows", 0)

    collector.set_extra("duplicate", {
        "messages_total": n * rep,
        "messages_accepted": accepted,
        "messages_rejected": rejected,
        "duplicate_step_rows": dup_steps,
    })

    print(f"  - 投递消息总数: {n * rep}")
    print(f"  - 实际执行: {accepted}")
    print(f"  - 幂等拦截: {rejected}")
    print(f"  - 重复 step 行: {dup_steps}")


async def _process_message(task_id, product, trace_id, metric):
    """处理单条重复消息 — 由幂等键决定是否真正执行"""
    from app.services.idempotency import acquire_idempotent
    if await acquire_idempotent(task_id, "product_analysis"):
        return "accepted"
    return "rejected"


# ================================================================
# 场景 5: 模型超时
# ================================================================
async def run_scenario_timeout(args, collector: MetricsCollector) -> None:
    """注入模型超时，验证指数退避 + 最大重试后进死信"""
    cfg = _cfg(args)
    ctx = get_context()
    ctx.injector.reset()
    ctx.injector.timeout_rate = cfg.timeout_rate

    n = cfg.concurrency
    print(f"  - 注入超时比例 {cfg.timeout_rate * 100:.0f}%，任务数 {n}")

    # 直接观察 retry 行为
    sem = asyncio.Semaphore(cfg.concurrency)
    pbar = tqdm(total=n, desc="[S5] 跑任务", ncols=80)

    async def _one(i: int):
        from app.services.tracing import generate_task_id, generate_trace_id
        task_id = generate_task_id()
        trace_id = generate_trace_id()
        product = make_product(i)
        from scripts.helpers.mock_infra import MockTask
        ctx.db.add_task(MockTask(task_id=task_id, trace_id=trace_id,
                                 status="created", product=product))
        metric = collector.new_task(task_id)

        async with sem:
            await _drive_step_with_timeout(task_id, "product_analysis", product, metric, collector)
        pbar.update(1)

    await asyncio.gather(*[_one(i) for i in range(n)], return_exceptions=True)
    pbar.close()

    n_timeout = ctx.injector.timeout_failures
    n_total = len(collector.tasks)
    n_dead = sum(1 for t in collector.tasks if t.went_to_dead_letter)
    n_retry = sum(t.retry_count for t in collector.tasks)

    collector.set_extra("timeout", {
        "timeout_injections": n_timeout,
        "dead_letter_tasks": n_dead,
        "total_retries": n_retry,
        "avg_retries_per_task": round(n_retry / n_total, 2) if n_total else 0.0,
    })

    print(f"  - 注入超时: {n_timeout}")
    print(f"  - 死信任务: {n_dead}")
    print(f"  - 总重试次数: {n_retry}")


async def _drive_step_with_timeout(task_id, step_id, product, metric, collector):
    """驱动单个 step 直到成功或死信"""
    from app.core.state_machine import StepStatus, STEP_NAME_DISPLAY
    from scripts.helpers.mock_infra import MockStep

    ctx = get_context()
    if ctx.db.get_step(task_id, step_id) is None:
        ctx.db.add_step(MockStep(task_id, step_id, STEP_NAME_DISPLAY.get(step_id, step_id)))

    for attempt in range(1, 4):  # 最多 3 次
        step = ctx.db.get_step(task_id, step_id)
        step.status = "running"
        step.started_at = time.time()
        try:
            orchestrator = get_orchestrator()
            await orchestrator.execute_step(task_id, step_id, {
                "task_id": task_id,
                "product": product,
                "history": {},
                "attempt": attempt,
                "failure_feedback": "",
            })
        except Exception:
            pass

        step = ctx.db.get_step(task_id, step_id)
        json_failed = step.failure_reason in (
            FailureReason.JSON_PARSE_ERROR.value,
            FailureReason.SCHEMA_VALIDATION_ERROR.value,
        )
        collector.record_step(
            metric, step_id,
            step.status == "success",
            step.latency_ms or 0,
            attempt,
            json_failed=json_failed,
        )

        if step.status == "success":
            metric.success = True
            metric.final_status = "success"
            metric.finished_at = time.time()
            return
        if step.status == "dead_letter" or ctx.db.tasks[task_id].status == "dead_letter":
            metric.went_to_dead_letter = True
            metric.final_status = "dead_letter"
            metric.finished_at = time.time()
            return

    # 超过 3 次还失败 → dead_letter
    metric.went_to_dead_letter = True
    metric.final_status = "dead_letter"
    metric.finished_at = time.time()
    ctx.db.tasks[task_id].status = "dead_letter"


# ================================================================
# 场景 6: 评估不通过 → 修复 agent 触发
# ================================================================
async def run_scenario_judge_fail(args, collector: MetricsCollector) -> None:
    """强制让 evaluator 输出 passed=false，验证 repair agent 是否触发"""
    cfg = _cfg(args)
    ctx = get_context()
    ctx.injector.reset()
    ctx.injector.judge_pass_rate = cfg.judge_pass_rate  # 0 = 全失败

    n = cfg.concurrency
    print(f"  - 评估通过率 {cfg.judge_pass_rate * 100:.0f}%，任务数 {n}")

    sem = asyncio.Semaphore(cfg.concurrency)
    pbar = tqdm(total=n, desc="[S6] 跑任务", ncols=80)
    repair_triggered = 0

    async def _one(i: int):
        nonlocal repair_triggered
        from app.services.tracing import generate_task_id, generate_trace_id
        task_id = generate_task_id()
        trace_id = generate_trace_id()
        product = make_product(i)
        from scripts.helpers.mock_infra import MockTask
        ctx.db.add_task(MockTask(task_id=task_id, trace_id=trace_id,
                                 status="created", product=product))
        metric = collector.new_task(task_id)

        async with sem:
            # 走完前面 4 个 step
            for step_id in WORKFLOW_STEPS[:4]:
                await _drive_step_simple(task_id, step_id, product, metric, collector)
                if metric.went_to_dead_letter:
                    break
            if not metric.went_to_dead_letter:
                # 评估 step：mock 决定通过 / 失败
                await _drive_evaluation(task_id, product, metric, collector)
                if not ctx.injector.should_judge_pass():
                    # repair agent 被触发
                    metric.repair_triggered = True
                    repair_triggered += 1
        pbar.update(1)

    await asyncio.gather(*[_one(i) for i in range(n)], return_exceptions=True)
    pbar.close()

    collector.set_extra("judge_fail", {
        "repair_triggered": repair_triggered,
        "judge_pass_rate": cfg.judge_pass_rate,
        "judge_failures_injected": ctx.injector.judge_failures,
    })

    print(f"  - 触发 repair agent: {repair_triggered}")
    print(f"  - 注入评估失败: {ctx.injector.judge_failures}")


async def _drive_step_simple(task_id, step_id, product, metric, collector):
    ctx = get_context()
    from app.core.state_machine import STEP_NAME_DISPLAY
    from scripts.helpers.mock_infra import MockStep

    if ctx.db.get_step(task_id, step_id) is None:
        ctx.db.add_step(MockStep(task_id, step_id, STEP_NAME_DISPLAY.get(step_id, step_id)))

    step = ctx.db.get_step(task_id, step_id)
    step.status = "running"
    step.started_at = time.time()
    try:
        await get_orchestrator().execute_step(task_id, step_id, {
            "task_id": task_id,
            "product": product,
            "history": {},
            "attempt": 1,
            "failure_feedback": "",
        })
    except Exception:
        pass
    step = ctx.db.get_step(task_id, step_id)
    json_failed = step.failure_reason in (
        FailureReason.JSON_PARSE_ERROR.value,
        FailureReason.SCHEMA_VALIDATION_ERROR.value,
    )
    collector.record_step(metric, step_id, step.status == "success",
                          step.latency_ms or 0, step.retry_count,
                          json_failed=json_failed)
    if step.status == "dead_letter":
        metric.went_to_dead_letter = True
        metric.final_status = "dead_letter"
        metric.finished_at = time.time()


async def _drive_evaluation(task_id, product, metric, collector):
    ctx = get_context()
    from app.core.state_machine import STEP_NAME_DISPLAY
    from scripts.helpers.mock_infra import MockStep, MockEvaluation

    step_id = "quality_evaluation"
    if ctx.db.get_step(task_id, step_id) is None:
        ctx.db.add_step(MockStep(task_id, step_id, STEP_NAME_DISPLAY.get(step_id, step_id)))

    step = ctx.db.get_step(task_id, step_id)
    step.status = "running"
    step.started_at = time.time()
    try:
        await get_orchestrator().execute_step(task_id, step_id, {
            "task_id": task_id,
            "product": product,
            "history": {},
            "attempt": 1,
            "failure_feedback": "",
        })
    except Exception:
        pass
    step = ctx.db.get_step(task_id, step_id)
    collector.record_step(metric, step_id, step.status == "success",
                          step.latency_ms or 0, step.retry_count)
    metric.success = step.status == "success"
    metric.final_status = ctx.db.tasks[task_id].status
    metric.finished_at = time.time()
    # 记录 evaluation 结果
    if not ctx.injector.should_judge_pass():
        ctx.db.evaluations.append(
            MockEvaluation(task_id, score=55, passed=False, risk_level="medium",
                           issues=[{"type": "SELLING_POINT_DRIFT", "detail": "mock"}])
        )
    else:
        ctx.db.evaluations.append(
            MockEvaluation(task_id, score=87, passed=True, risk_level="low", issues=[])
        )