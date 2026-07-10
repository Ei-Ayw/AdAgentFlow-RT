"""Deterministic fault plans shared across runtime methods."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List


@dataclass(frozen=True)
class FaultPlanEntry:
    benchmark: str
    domain: str
    task_id: str
    trial_id: int
    stressor: str
    phase: str
    attempt: int
    injection_point: str
    fault_seed: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_fault_plan(*, task: Any, stressors: Iterable[Any], max_attempts: int) -> List[FaultPlanEntry]:
    plan: List[FaultPlanEntry] = []
    for stressor in stressors:
        rate = float(getattr(stressor, "rate", 0.0) or 0.0)
        if rate <= 0.0:
            continue
        for attempt in range(1, max(1, max_attempts) + 1):
            key = "|".join(
                [
                    str(task.benchmark),
                    str(task.domain),
                    str(task.task_id),
                    str(task.trial_id),
                    str(getattr(stressor, "name", "base")),
                    "node",
                    str(attempt),
                ]
            )
            digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
            roll = int(digest[:8], 16) / 0xFFFFFFFF
            if roll >= rate:
                continue
            plan.append(
                FaultPlanEntry(
                    benchmark=str(task.benchmark),
                    domain=str(task.domain),
                    task_id=str(task.task_id),
                    trial_id=int(task.trial_id),
                    stressor=str(getattr(stressor, "name", "base")),
                    phase="node",
                    attempt=attempt,
                    injection_point=f"node:{attempt}",
                    fault_seed=int(digest[8:16], 16),
                )
            )
    return plan


def planned_faults_for(
    *,
    fault_plan: Iterable[FaultPlanEntry | Dict[str, Any]],
    stressor_name: str,
    phase: str,
    attempt: int,
) -> List[FaultPlanEntry]:
    matched: List[FaultPlanEntry] = []
    for item in fault_plan:
        entry = item if isinstance(item, FaultPlanEntry) else FaultPlanEntry(**item)
        if entry.stressor == stressor_name and entry.phase == phase and entry.attempt == attempt:
            matched.append(entry)
    return matched
