"""Runtime reliability metrics."""
from __future__ import annotations

from statistics import median
from typing import Any, Dict, Iterable, List

from experiments.harness.metrics.trace_metrics import compute_trace_metrics
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
    trace_metrics = [compute_trace_metrics(row.events) for row in rows]
    detect_times = [m["time_to_detect_ms"] for m in trace_metrics if m["time_to_detect_ms"] > 0]
    recover_times = [m["time_to_recover_ms"] for m in trace_metrics if m["time_to_recover_ms"] > 0]
    fault_class_counts: Dict[str, int] = {}
    recovery_action_counts: Dict[str, int] = {}
    for metrics in trace_metrics:
        for key, value in metrics["fault_class_counts"].items():
            fault_class_counts[key] = fault_class_counts.get(key, 0) + value
        for key, value in metrics["recovery_action_counts"].items():
            recovery_action_counts[key] = recovery_action_counts.get(key, 0) + value
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
        "fault_propagation_depth": max(
            [row.runtime_metrics.get("fault_propagation_depth", 0) for row in rows]
            + [metrics["fault_propagation_depth"] for metrics in trace_metrics],
            default=0,
        ),
        "contaminated_artifact_count": sum(
            max(row.runtime_metrics.get("contaminated_artifact_count", 0), metrics["contaminated_artifact_count"])
            for row, metrics in zip(rows, trace_metrics)
        ),
        "mean_time_to_detect_ms": int(sum(detect_times) / len(detect_times)) if detect_times else 0,
        "mean_time_to_recover_ms": int(sum(recover_times) / len(recover_times)) if recover_times else 0,
        "trace_event_count": sum(metrics["event_count"] for metrics in trace_metrics),
        "fault_class_counts": fault_class_counts,
        "recovery_action_counts": recovery_action_counts,
    }
