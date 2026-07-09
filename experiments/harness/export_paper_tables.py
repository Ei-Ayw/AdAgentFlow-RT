"""Export paper-facing CSV tables from aggregated experiment summaries."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


MAIN_FIELDS = [
    "benchmark",
    "domain",
    "method",
    "ablation",
    "benchmark_adapter_mode",
    "task_success",
    "task_success_rate",
    "p95_latency_ms",
    "dead_letter_rate",
    "recovery_success_rate",
    "cost_per_successful_task",
]

RUNTIME_FIELDS = [
    "benchmark",
    "domain",
    "method",
    "ablation",
    "contract_violation_rate",
    "silent_failure_rate",
    "retry_amplification_factor",
    "extra_tool_calls",
    "extra_llm_calls",
    "fault_propagation_depth",
    "contaminated_artifact_count",
    "mean_time_to_detect_ms",
    "mean_time_to_recover_ms",
    "trace_event_count",
]

AGENTCHANGE_FIELDS = [
    "benchmark",
    "domain",
    "method",
    "TSR",
    "TUE",
    "TCRR",
    "GSRT",
    "recovery_success_rate",
    "mean_time_to_recover_ms",
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
    write_table(table_dir / "runtime_stability_metrics.csv", rows, RUNTIME_FIELDS)
    write_table(table_dir / "agentchange_recovery_metrics.csv", [row for row in rows if row.get("benchmark") == "agentchange"], AGENTCHANGE_FIELDS)
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
