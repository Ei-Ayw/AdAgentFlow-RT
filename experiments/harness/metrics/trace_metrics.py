"""Trace metric helpers."""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable


def compute_trace_metrics(events: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    event_list = list(events)
    by_type = Counter(event.get("event_type") for event in event_list)
    fault_localizations = [event for event in event_list if event.get("event_type") == "fault.localized"]
    recovery_actions = [
        event.get("payload", {}).get("action") or event.get("status")
        for event in event_list
        if event.get("event_type") in {"recovery.selected", "recovery.succeeded", "recovery.failed"}
    ]
    injected_at = _first_relative_ms(event_list, "fault.injected")
    violated_at = _first_relative_ms(event_list, "contract.violated")
    recovered_at = _first_relative_ms(event_list, "recovery.succeeded")
    failed_at = _first_relative_ms(event_list, "recovery.failed")
    finished_recovery_at = recovered_at if recovered_at else failed_at
    propagation_depth = 0
    contaminated = 0
    fault_classes = Counter()
    for event in fault_localizations:
        payload = event.get("payload", {})
        affected = payload.get("affected_downstream_nodes") or []
        artifacts = payload.get("contaminated_artifacts") or []
        propagation_depth = max(propagation_depth, len(affected))
        contaminated += len(set(artifacts))
        fault_class = payload.get("fault_class")
        if fault_class:
            fault_classes[fault_class] += 1
    return {
        "event_count": len(event_list),
        "event_types": dict(by_type),
        "has_recovery_trace": any(event.get("event_type") == "recovery.selected" for event in event_list),
        "fault_propagation_depth": propagation_depth,
        "contaminated_artifact_count": contaminated,
        "time_to_detect_ms": max(0, violated_at - injected_at) if injected_at and violated_at else 0,
        "time_to_recover_ms": max(0, finished_recovery_at - violated_at) if finished_recovery_at and violated_at else 0,
        "fault_class_counts": dict(fault_classes),
        "recovery_action_counts": dict(Counter(action for action in recovery_actions if action)),
    }


def _first_relative_ms(events: list[Dict[str, Any]], event_type: str) -> int:
    for event in events:
        if event.get("event_type") == event_type:
            return int((event.get("payload") or {}).get("relative_ms") or 0)
    return 0
