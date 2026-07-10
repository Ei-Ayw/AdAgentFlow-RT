"""Export paper-facing CSV tables from aggregated experiment summaries."""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List


# Field set for the main tau3 results table.
#
# ``task_success`` / ``task_success_rate`` are kept as backwards-compat
# aliases of ``fixture_success_rate`` / ``runtime_success_rate``.  The
# paper text now uses the explicit pair so reviewers can see which
# notion of success is being quoted.  ``over_rejection_rate`` is the
# false-dead-letter signal that closes the "silent failure = 0" gap
# raised in the AAMAS revision.
MAIN_FIELDS = [
    "benchmark",
    "domain",
    "method",
    "ablation",
    "benchmark_adapter_mode",
    "fixture_success_rate",
    "runtime_success_rate",
    "over_rejection_rate",
    "task_success",
    "task_success_rate",
    "p95_latency_ms",
    "dead_letter_rate",
    "recovery_success_rate",
    "cost_per_successful_task",
]

RUNTIME_FIELDS = [
    "method",
    "ablation",
    "n_cells",
    "total_tasks",
    "contract_violation_rate",
    "silent_failure_rate",
    "over_rejection_rate",
    "dead_letter_rate",
    "retry_amplification_factor",
    "extra_tool_calls",
    "extra_llm_calls",
    "fault_propagation_depth",
    "contaminated_artifact_count",
    "mean_time_to_detect_ms",
    "mean_time_to_recover_ms",
    "trace_event_count",
]

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="append", required=True)
    parser.add_argument("--table-dir", default="paper/aamas2026/tables")
    args = parser.parse_args()

    rows = load_summaries(args.summary)
    table_dir = Path(args.table_dir)
    table_dir.mkdir(parents=True, exist_ok=True)

    write_table(table_dir / "main_tau3_results.csv", [row for row in rows if row.get("benchmark") in {"tau3", "mock"}], MAIN_FIELDS)
    write_table(table_dir / "runtime_stability_metrics.csv", aggregate_runtime_rows(rows), RUNTIME_FIELDS)
    write_failure_breakdown(table_dir / "failure_recovery_breakdown.csv", rows)


def load_summaries(paths: Iterable[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            rows.extend(data)
        else:
            rows.append(data)
    return rows


def write_table(path: Path, rows: List[Dict[str, Any]], fields: List[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fields})


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _total_tasks(row: Dict[str, Any]) -> int:
    try:
        return int(row.get("total_tasks") or 0)
    except (TypeError, ValueError):
        return 0


def _weighted_mean(rows: List[Dict[str, Any]], field: str) -> float:
    total_tasks = sum(_total_tasks(row) for row in rows)
    if total_tasks <= 0:
        return 0.0
    total = sum(_as_float(row.get(field)) * _total_tasks(row) for row in rows)
    return total / total_tasks


def _per_task_total(rows: List[Dict[str, Any]], field: str) -> float:
    total_tasks = sum(_total_tasks(row) for row in rows)
    if total_tasks <= 0:
        return 0.0
    total = sum(_as_float(row.get(field)) for row in rows)
    return total / total_tasks


def aggregate_runtime_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("benchmark") not in {"tau3", "mock"}:
            continue
        grouped[(str(row.get("method") or ""), str(row.get("ablation") or ""))].append(row)

    aggregated: List[Dict[str, Any]] = []
    for method, ablation in sorted(grouped):
        group = grouped[(method, ablation)]
        aggregated.append(
            {
                "method": method,
                "ablation": ablation,
                "n_cells": len(group),
                "total_tasks": sum(_total_tasks(row) for row in group),
                "contract_violation_rate": _weighted_mean(group, "contract_violation_rate"),
                "silent_failure_rate": _weighted_mean(group, "silent_failure_rate"),
                "over_rejection_rate": _weighted_mean(group, "over_rejection_rate"),
                "dead_letter_rate": _weighted_mean(group, "dead_letter_rate"),
                "retry_amplification_factor": _weighted_mean(group, "retry_amplification_factor"),
                "extra_tool_calls": _per_task_total(group, "extra_tool_calls"),
                "extra_llm_calls": _per_task_total(group, "extra_llm_calls"),
                "fault_propagation_depth": max((_as_float(row.get("fault_propagation_depth")) for row in group), default=0.0),
                "contaminated_artifact_count": _per_task_total(group, "contaminated_artifact_count"),
                "mean_time_to_detect_ms": _weighted_mean(group, "mean_time_to_detect_ms"),
                "mean_time_to_recover_ms": _weighted_mean(group, "mean_time_to_recover_ms"),
                "trace_event_count": _per_task_total(group, "trace_event_count"),
            }
        )
    return aggregated


def write_failure_breakdown(path: Path, rows: List[Dict[str, Any]]) -> None:
    fields = ["benchmark", "domain", "method", "ablation", "fault_class", "count", "recovery_actions"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            fault_counts = row.get("fault_class_counts") or {}
            recovery_actions = row.get("recovery_action_counts") or {}
            if not fault_counts:
                writer.writerow(
                    {
                        "benchmark": row.get("benchmark"),
                        "domain": row.get("domain"),
                        "method": row.get("method"),
                        "ablation": row.get("ablation"),
                        "fault_class": "none",
                        "count": 0,
                        "recovery_actions": recovery_actions,
                    }
                )
                continue
            for fault_class, count in sorted(fault_counts.items()):
                writer.writerow(
                    {
                        "benchmark": row.get("benchmark"),
                        "domain": row.get("domain"),
                        "method": row.get("method"),
                        "ablation": row.get("ablation"),
                        "fault_class": fault_class,
                        "count": count,
                        "recovery_actions": recovery_actions,
                    }
                )


if __name__ == "__main__":
    main()
