"""Bounded recovery decision logic."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

from app.contracts.models import ContractViolation
from app.contracts.policies import DEFAULT_RECOVERY_POLICY, TERMINAL_ACTIONS
from app.runtime.fault_localizer import FaultDiagnosis


@dataclass
class RecoveryDecision:
    action: str
    target_node: str
    reason: str
    budget_cost: Dict[str, Any] = field(default_factory=dict)
    should_continue: bool = True


class RecoveryController:
    def select(
        self,
        *,
        violation: ContractViolation,
        diagnosis: FaultDiagnosis,
        remaining_budget: Dict[str, int],
    ) -> RecoveryDecision:
        policy_actions = DEFAULT_RECOVERY_POLICY.get(
            violation.violation_type,
            DEFAULT_RECOVERY_POLICY["UNKNOWN"],
        )
        candidates = diagnosis.recommended_recovery or policy_actions
        for action in candidates:
            if action not in policy_actions and action != "invalidate_downstream":
                continue
            if _has_budget(action, remaining_budget):
                return RecoveryDecision(
                    action=action,
                    target_node=diagnosis.responsible_node,
                    reason=f"{diagnosis.fault_class}:{violation.violation_type}",
                    budget_cost=_cost(action),
                    should_continue=action not in TERMINAL_ACTIONS,
                )
        return RecoveryDecision(
            action="dead_letter",
            target_node=diagnosis.responsible_node,
            reason="no recovery action available within budget",
            budget_cost={},
            should_continue=False,
        )


def _cost(action: str) -> Dict[str, Any]:
    if action in {"quick_repair", "invalidate_downstream"}:
        return {"recovery_steps": 1}
    if action in {"retry_same_agent", "reroute_agent", "rollback_to_checkpoint"}:
        return {"retries": 1, "recovery_steps": 1}
    return {"terminal": True}


def _has_budget(action: str, remaining_budget: Dict[str, int]) -> bool:
    if action in {"retry_same_agent", "reroute_agent", "rollback_to_checkpoint"}:
        return int(remaining_budget.get("retries", 0)) > 0
    return True
