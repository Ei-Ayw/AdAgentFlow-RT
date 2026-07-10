"""Runtime reliability metrics.

The current code distinguishes three success / failure concepts that are
commonly conflated in LLM-agent evaluation, and emits all three so the
paper can quote whichever one is meaningful for a given claim:

* ``fixture_success`` (was ``task_success``): the benchmark-native scorer
  considers the agent's final trajectory consistent with the public
  assertions / policy.  This is what a benchmark paper would report.
* ``runtime_success`` (was ``task_success_rate``): the contractual runtime
  considers the run completed cleanly (no dead-letter, no contract
  recovery failed).  This is the "did the runtime keep the workflow
  alive" question.
* ``over_rejection_rate`` (new): the fraction of runs where the fixture
  scorer said success but the runtime still dead-lettered.  This is the
  audit signal that closes the gap "silent failure = 0 is meaningless if
  the runtime is just dead-lettering everything it disagrees with".

A run that is dead-lettered by the runtime but scored successful by the
fixture is the canonical example of a "false dead-letter / over-
rejection".  Conversely, a run that the fixture rejects but the runtime
marks successful is a "silent failure".  All four configurations
currently report zero measured silent failures, so over-rejection is the
metric that actually bears the burden of evidence.
"""
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
    # Fixture-native success: the benchmark's public scorer (NL assertions /
    # policy compliance) considers the final trajectory OK.
    fixture_successes = sum(
        1
        for row in rows
        if row.native_metrics.get("task_success") is True
    )
    # Runtime success: the contractual runtime finalised the run cleanly
    # (no dead-letter, contract recovery did not fail).
    runtime_successes = sum(
        1 for row in rows if row.success and not row.dead_letter
    )
    successes = runtime_successes  # backwards-compat alias used by tables.
    dead_letters = sum(1 for row in rows if row.dead_letter)
    recovered = sum(1 for row in rows if row.recovered)
    # "Bounded recovery" only counts runs that used the recovery
    # controller (bounded_recovery_actions > 0), not the schema-only
    # quick repair path.  This is the metric the paper reports, and it
    # is what makes ``without_bounded_recovery`` ablation show zero.
    bounded_recovered = sum(
        1
        for row in rows
        if (row.runtime_metrics.get("bounded_recovery_actions") or 0) > 0
        and row.success
    )
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
    # Silent failure: runtime reported success, fixture rejected.
    silent_failure = sum(
        1
        for row in rows
        if row.success
        and row.native_metrics.get("task_success") is False
    )
    # Over-rejection (false dead-letter): fixture would have accepted the
    # trajectory, runtime still dead-lettered it.  This is the new metric
    # required by the AAMAS revision.  When the fixture scorer is absent
    # (e.g. internal mock mode) we conservatively treat the run as not
    # over-rejected, so the metric stays defined for every cell.
    over_rejection = sum(
        1
        for row in rows
        if row.dead_letter
        and row.native_metrics.get("task_success") is True
    )
    elapsed_min = max(1.0 / 60.0, sum(latencies) / 60000.0)
    return {
        "total_tasks": total,
        # New explicit names (preferred for paper text and Table 1).
        "fixture_success_rate": fixture_successes / total if total else 0.0,
        "runtime_success_rate": runtime_successes / total if total else 0.0,
        "over_rejection_rate": over_rejection / total if total else 0.0,
        # Backwards-compat aliases retained so existing paper tables do
        # not silently change meaning; they now point at runtime success
        # for ``task_success_rate`` and at fixture success for
        # ``task_success``.  The paper text in
        # ``paper/aamas2026/sections/experiments.tex`` is being updated
        # to use the new explicit names.
        "task_success": fixture_successes / total if total else 0.0,
        "task_success_rate": runtime_successes / total if total else 0.0,
        "throughput_tasks_per_min": total / elapsed_min if total else 0.0,
        "p50_latency_ms": int(median(latencies)) if latencies else 0,
        "p95_latency_ms": percentile(latencies, 0.95),
        "p99_latency_ms": percentile(latencies, 0.99),
        "dead_letter_rate": dead_letters / total if total else 0.0,
        # Bounded-recovery success: only the recovery controller
        # counts.  The historical ``recovery_success_rate`` field is
        # kept as an alias for back-compat with the previous paper
        # table; in new runs it points at the same value.
        "bounded_recovery_success_rate": bounded_recovered / recoverable_faults if recoverable_faults else 0.0,
        "recovery_success_rate": bounded_recovered / recoverable_faults if recoverable_faults else 0.0,
        "contract_violation_rate": sum(row.runtime_metrics.get("contract_violations", 0) for row in rows) / total if total else 0.0,
        "silent_failure_rate": silent_failure / marked_success,
        "retry_amplification_factor": attempts / total if total else 0.0,
        "extra_tool_calls": sum(max(0, row.tool_calls - 2) for row in rows),
        "extra_llm_calls": sum(max(0, row.llm_calls - 1) for row in rows),
        "cost_per_successful_task": total_cost / successes if successes else None,
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
