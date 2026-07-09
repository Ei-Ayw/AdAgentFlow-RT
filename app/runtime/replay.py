"""Replay utilities for event-sourced runtime traces."""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable

from app.runtime.event_log import RuntimeEvent


def summarize_events(events: Iterable[RuntimeEvent]) -> Dict[str, Any]:
    event_list = list(events)
    by_type = Counter(event.event_type for event in event_list)
    by_status = Counter(event.status for event in event_list)
    return {
        "event_count": len(event_list),
        "by_type": dict(by_type),
        "by_status": dict(by_status),
        "first_event_at": event_list[0].created_at if event_list else None,
        "last_event_at": event_list[-1].created_at if event_list else None,
    }
