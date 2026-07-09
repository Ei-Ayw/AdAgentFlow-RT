"""Fault localization for contract violations."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from app.contracts.models import ContractViolation
from app.runtime.graph import ContractualExecutionGraph


@dataclass
class FaultDiagnosis:
    fault_class: str
    responsible_node: str
    contaminated_artifacts: List[str]
    affected_downstream_nodes: List[str]
    confidence: float
    recommended_recovery: List[str] = field(default_factory=list)


class FaultLocalizer:
    def diagnose(
        self,
        *,
        graph: ContractualExecutionGraph,
        violation: ContractViolation,
    ) -> FaultDiagnosis:
        mapping = {
            "SCHEMA_VIOLATION": "artifact_fault",
            "PRECONDITION_FAILED": "coordination_fault",
            "POSTCONDITION_FAILED": "agent_local_fault",
            "SEMANTIC_DRIFT": "artifact_fault",
            "BUDGET_EXCEEDED": "resource_fault",
            "TOOL_FAILURE": "tool_environment_fault",
            "TIMEOUT": "tool_environment_fault",
            "DUPLICATE_EXECUTION": "runtime_fault",
            "STALE_CONTEXT": "coordination_fault",
        }
        fault_class = mapping.get(violation.violation_type, "runtime_fault")
        affected = _collect_downstream(graph, violation.node_id)
        contaminated = [
            edge.artifact
            for edge in graph.edges
            if edge.source == violation.node_id or edge.target in affected
        ]
        recovery = {
            "artifact_fault": ["quick_repair", "retry_same_agent", "invalidate_downstream"],
            "coordination_fault": ["rollback_to_checkpoint", "retry_same_agent"],
            "resource_fault": ["degrade_output", "dead_letter"],
            "tool_environment_fault": ["retry_same_agent", "reroute_agent"],
            "runtime_fault": ["dead_letter"],
        }.get(fault_class, ["dead_letter"])
        return FaultDiagnosis(
            fault_class=fault_class,
            responsible_node=violation.node_id,
            contaminated_artifacts=sorted(set(contaminated)),
            affected_downstream_nodes=affected,
            confidence=0.8 if fault_class != "runtime_fault" else 0.55,
            recommended_recovery=recovery,
        )


def _collect_downstream(graph: ContractualExecutionGraph, node_id: str) -> List[str]:
    seen: set[str] = set()
    stack = list(graph.downstream(node_id))
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(graph.downstream(current))
    return sorted(seen)
