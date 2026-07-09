"""Replay utilities for event-sourced runtime traces."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from app.runtime.event_log import RuntimeEvent


REQUIRED_TRACE_EVENTS = (
    "graph.created",
    "contract.loaded",
    "node.started",
    "contract.checked",
    "task.finalized",
)

ORDERED_TRACE_EVENTS = (
    "graph.created",
    "contract.loaded",
    "node.started",
    "contract.checked",
    "task.finalized",
)

RECOVERY_EVENTS = {
    "recovery.selected",
    "recovery.succeeded",
    "recovery.failed",
    "dead_letter.created",
}


@dataclass
class ReplayDiagnostic:
    event_count: int
    by_type: Dict[str, int]
    by_status: Dict[str, int]
    first_event_at: Optional[str]
    last_event_at: Optional[str]
    task_ids: List[str] = field(default_factory=list)
    run_ids: List[str] = field(default_factory=list)
    missing_required_events: List[str] = field(default_factory=list)
    ordering_errors: List[str] = field(default_factory=list)
    recovery_actions: List[str] = field(default_factory=list)
    terminal_status: Optional[str] = None

    @property
    def replayable(self) -> bool:
        return not self.missing_required_events and not self.ordering_errors

    @property
    def has_recovery_chain(self) -> bool:
        return bool(self.recovery_actions)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_count": self.event_count,
            "by_type": dict(self.by_type),
            "by_status": dict(self.by_status),
            "first_event_at": self.first_event_at,
            "last_event_at": self.last_event_at,
            "task_ids": list(self.task_ids),
            "run_ids": list(self.run_ids),
            "missing_required_events": list(self.missing_required_events),
            "ordering_errors": list(self.ordering_errors),
            "recovery_actions": list(self.recovery_actions),
            "terminal_status": self.terminal_status,
            "replayable": self.replayable,
            "has_recovery_chain": self.has_recovery_chain,
        }


def summarize_events(events: Iterable[RuntimeEvent | Dict[str, Any]]) -> Dict[str, Any]:
    return replay_trace(events).to_dict()


def replay_trace(events: Iterable[RuntimeEvent | Dict[str, Any]]) -> ReplayDiagnostic:
    event_list = [_event_to_dict(event) for event in events]
    by_type = Counter(str(event.get("event_type")) for event in event_list)
    by_status = Counter(str(event.get("status", "ok")) for event in event_list)
    event_types = [str(event.get("event_type")) for event in event_list]
    missing = [event_type for event_type in REQUIRED_TRACE_EVENTS if event_type not in by_type]
    recovery_actions = [
        str((event.get("payload") or {}).get("action") or event.get("status"))
        for event in event_list
        if event.get("event_type") in RECOVERY_EVENTS
        and ((event.get("payload") or {}).get("action") or event.get("status"))
    ]
    terminal = _terminal_status(event_list)
    ordering_errors = _ordering_errors(event_types)

    task_ids = sorted({str(event.get("task_id")) for event in event_list if event.get("task_id")})
    run_ids = sorted({str(event.get("run_id")) for event in event_list if event.get("run_id")})
    if len(task_ids) > 1:
        ordering_errors.append(f"trace spans multiple task_ids: {','.join(task_ids)}")
    if len(run_ids) > 1:
        ordering_errors.append(f"trace spans multiple run_ids: {','.join(run_ids)}")

    return ReplayDiagnostic(
        event_count=len(event_list),
        by_type=dict(by_type),
        by_status=dict(by_status),
        first_event_at=str(event_list[0].get("created_at")) if event_list else None,
        last_event_at=str(event_list[-1].get("created_at")) if event_list else None,
        task_ids=task_ids,
        run_ids=run_ids,
        missing_required_events=missing,
        ordering_errors=ordering_errors,
        recovery_actions=recovery_actions,
        terminal_status=terminal,
    )


def _event_to_dict(event: RuntimeEvent | Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(event, RuntimeEvent):
        return event.__dict__.copy()
    return dict(event)


def _ordering_errors(event_types: List[str]) -> List[str]:
    errors: List[str] = []
    positions = {event_type: _first_index(event_types, event_type) for event_type in ORDERED_TRACE_EVENTS}
    previous_type: Optional[str] = None
    previous_index: Optional[int] = None
    for event_type in ORDERED_TRACE_EVENTS:
        index = positions[event_type]
        if index is None:
            continue
        if previous_index is not None and index < previous_index:
            errors.append(f"{event_type} appears before {previous_type}")
        previous_type = event_type
        previous_index = index
    return errors


def _first_index(items: List[str], needle: str) -> Optional[int]:
    try:
        return items.index(needle)
    except ValueError:
        return None


def _terminal_status(events: List[Dict[str, Any]]) -> Optional[str]:
    for event in reversed(events):
        if event.get("event_type") == "task.finalized":
            return str(event.get("status", "ok"))
    for event in reversed(events):
        if event.get("event_type") == "dead_letter.created":
            return "dead_letter"
    return None
