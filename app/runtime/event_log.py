"""Event-sourced runtime trace primitives."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4


@dataclass
class RuntimeEvent:
    event_id: str
    run_id: str
    task_id: str
    event_type: str
    node_id: Optional[str] = None
    status: str = "ok"
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class InMemoryEventLog:
    def __init__(self):
        self.events: List[RuntimeEvent] = []

    def record(
        self,
        *,
        run_id: str,
        task_id: str,
        event_type: str,
        node_id: Optional[str] = None,
        status: str = "ok",
        payload: Optional[Dict[str, Any]] = None,
    ) -> RuntimeEvent:
        event = RuntimeEvent(
            event_id=f"evt_{uuid4().hex}",
            run_id=run_id,
            task_id=task_id,
            event_type=event_type,
            node_id=node_id,
            status=status,
            payload=payload or {},
        )
        self.events.append(event)
        return event

    def by_task(self, task_id: str) -> List[RuntimeEvent]:
        return [event for event in self.events if event.task_id == task_id]

    def to_dicts(self) -> List[Dict[str, Any]]:
        return [event.__dict__.copy() for event in self.events]
