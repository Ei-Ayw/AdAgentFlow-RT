"""Reliability surface helpers."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, Tuple

from experiments.harness.runtime_adapters.base import RuntimeResult


def group_success_by_method_domain(results: Iterable[RuntimeResult]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    groups: dict[Tuple[str, str], list[RuntimeResult]] = defaultdict(list)
    for result in results:
        groups[(result.method, result.domain)].append(result)
    return {
        key: {
            "tasks": len(rows),
            "success_rate": sum(1 for row in rows if row.success) / len(rows),
        }
        for key, rows in groups.items()
    }
