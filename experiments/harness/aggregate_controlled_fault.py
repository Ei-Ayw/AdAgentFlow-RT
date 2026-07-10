"""Aggregate the controlled fault-injection results into a paper table.

For each (method, stressor) pair we report task-weighted means of:

* containment_rate              -- runtime detected the fault
* bounded_recovery_used_rate    -- recovery controller fired
* final_runtime_success_rate    -- replay runtime success
* final_fixture_success_rate    -- replay fixture success
* mean_contaminated_artifact_count
* mean_delta_contaminated_artifact_count
* over_rejection_rate           -- false dead-letter

This is the table that turns the main matrix from "aggregate robustness"
into per-fault causal evidence.

Run from the repo root:

    .venv/bin/python -m experiments.harness.aggregate_controlled_fault \\
        --input-dir experiments/results/main/real_full_v2/controlled_fault \\
        --output paper/aamas2026/tables/controlled_fault_table.csv
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional


def _safe_mean(values: List[float]) -> Optional[float]:
    cleaned = [v for v in values if v is not None]
    return mean(cleaned) if cleaned else None


def aggregate_controlled_fault(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[tuple, List[Dict[str, Any]]] = {}
    for row in rows:
        key = (row.get("method"), row.get("stressor"))
        grouped.setdefault(key, []).append(row)

    aggregated: List[Dict[str, Any]] = []
    for (method, stressor), group in sorted(grouped.items()):
        aggregated.append(
            {
                "method": method or "",
                "stressor": stressor or "",
                "n_tasks": len(group),
                "containment_rate": _safe_mean([float(r.get("containment") or 0) for r in group]),
                "bounded_recovery_used_rate": _safe_mean(
                    [float(r.get("bounded_recovery_used") or 0) for r in group]
                ),
                "final_runtime_success_rate": _safe_mean(
                    [float(r.get("runtime_success") or 0) for r in group]
                ),
                "final_fixture_success_rate": _safe_mean(
                    [float(r.get("fixture_success") or 0) for r in group]
                ),
                "over_rejection_rate": _safe_mean(
                    [float(r.get("over_rejection") or 0) for r in group]
                ),
                "mean_contaminated_artifact_count": _safe_mean(
                    [float(r.get("contaminated_artifact_count") or 0) for r in group]
                ),
                "mean_delta_contaminated_artifact_count": _safe_mean(
                    [float(r.get("delta_contaminated_artifact_count") or 0) for r in group]
                ),
            }
        )
    return aggregated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True,
                        help="Directory containing controlled_<stressor>.jsonl files")
    parser.add_argument("--output", default="paper/aamas2026/tables/controlled_fault_table.csv")
    args = parser.parse_args()

    rows: List[Dict[str, Any]] = []
    for path in sorted(Path(args.input_dir).glob("controlled_*.jsonl")):
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                rows.append(json.loads(line))

    aggregated = aggregate_controlled_fault(rows)
    fields = [
        "method",
        "stressor",
        "n_tasks",
        "containment_rate",
        "bounded_recovery_used_rate",
        "final_runtime_success_rate",
        "final_fixture_success_rate",
        "over_rejection_rate",
        "mean_contaminated_artifact_count",
        "mean_delta_contaminated_artifact_count",
    ]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in aggregated:
            writer.writerow({field: row.get(field) for field in fields})
    print(f"wrote {len(aggregated)} (method, stressor) rows to {output}")


if __name__ == "__main__":
    main()
