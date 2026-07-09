"""Trace metric helpers."""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable


def compute_trace_metrics(events: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    event_list = list(events)
    by_type = Counter(event.get("event_type") for event in event_list)
    return {
        "event_count": len(event_list),
        "event_types": dict(by_type),
        "has_recovery_trace": any(event.get("event_type") == "recovery.selected" for event in event_list),
    }
