"""Benchmark-native metric aggregation."""
from __future__ import annotations

from typing import Any, Dict, Iterable

from experiments.harness.runtime_adapters.base import RuntimeResult


def compute_benchmark_metrics(results: Iterable[RuntimeResult]) -> Dict[str, Any]:
    rows = list(results)
    total = len(rows)
    return {
        "task_success": sum(1 for row in rows if row.native_metrics.get("task_success")) / total if total else 0.0,
        "policy_compliance": sum(1 for row in rows if _actual_policy_compliance(row)) / total if total else 0.0,
        "TSR": _mean_native(rows, "TSR"),
        "TUE": _mean_native(rows, "TUE"),
        "TCRR": _mean_native(rows, "TCRR"),
        "GSRT": _mean_native(rows, "GSRT"),
    }


def _actual_policy_compliance(row: RuntimeResult) -> bool:
    if "policy_compliance" in row.native_metrics:
        return bool(row.native_metrics["policy_compliance"])
    return bool(row.native_metrics.get("policy_compliance_expected", True))


def _mean_native(rows: list[RuntimeResult], key: str):
    values = [row.native_metrics[key] for row in rows if isinstance(row.native_metrics.get(key), (int, float))]
    return sum(values) / len(values) if values else None
