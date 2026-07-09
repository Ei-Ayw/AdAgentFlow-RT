"""Runtime reliability metrics."""
from __future__ import annotations

from statistics import median
from typing import Any, Dict, Iterable, List

from experiments.harness.runtime_adapters.base import RuntimeResult


def percentile(values: List[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round((len(ordered) - 1) * q)))
    return int(ordered[idx])


def compute_runtime_metrics(results: Iterable[RuntimeResult]) -> Dict[str, Any]:
    rows = list(results)
    total = len(rows)
    successes = sum(1 for row in rows if row.success)
    dead_letters = sum(1 for row in rows if row.dead_letter)
    recovered = sum(1 for row in rows if row.recovered)
    recoverable_faults = sum(1 for row in rows if row.injected_faults or row.runtime_metrics.get("contract_violations", 0))
    attempts = sum(row.attempts for row in rows)
    latencies = [row.latency_ms for row in rows]
    total_cost = sum(row.llm_calls + row.tool_calls for row in rows)
    marked_success = max(1, successes)
    native_failed_success = sum(
        1
        for row in rows
        if row.success and row.native_metrics.get("task_success") is False
    )
    elapsed_min = max(1.0 / 60.0, sum(latencies) / 60000.0)
    return {
        "total_tasks": total,
        "task_success_rate": successes / total if total else 0.0,
        "throughput_tasks_per_min": total / elapsed_min if total else 0.0,
        "p50_latency_ms": int(median(latencies)) if latencies else 0,
        "p95_latency_ms": percentile(latencies, 0.95),
        "p99_latency_ms": percentile(latencies, 0.99),
        "dead_letter_rate": dead_letters / total if total else 0.0,
        "recovery_success_rate": recovered / recoverable_faults if recoverable_faults else 0.0,
        "contract_violation_rate": sum(row.runtime_metrics.get("contract_violations", 0) for row in rows) / total if total else 0.0,
        "silent_failure_rate": native_failed_success / marked_success,
        "retry_amplification_factor": attempts / total if total else 0.0,
        "extra_tool_calls": sum(max(0, row.tool_calls - 2) for row in rows),
        "extra_llm_calls": sum(max(0, row.llm_calls - 1) for row in rows),
        "cost_per_successful_task": total_cost / successes if successes else 0.0,
        "fault_propagation_depth": max((row.runtime_metrics.get("fault_propagation_depth", 0) for row in rows), default=0),
        "contaminated_artifact_count": sum(row.runtime_metrics.get("contaminated_artifact_count", 0) for row in rows),
        "mean_time_to_detect_ms": 0,
        "mean_time_to_recover_ms": int(sum(row.latency_ms for row in rows if row.recovered) / recovered) if recovered else 0,
    }
