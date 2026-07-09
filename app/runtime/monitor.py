"""Runtime contract monitor."""
from __future__ import annotations

from typing import Any, Dict, List

from app.contracts.models import ContractViolation
from app.contracts.registry import ContractRegistry
from app.contracts.validators import check_budget, check_required_artifacts, validate_schema
from app.runtime.artifact_store import InMemoryArtifactStore
from app.runtime.graph import ContractualExecutionGraph, RuntimeNode


class RuntimeMonitor:
    def __init__(self, registry: ContractRegistry, artifact_store: InMemoryArtifactStore):
        self.registry = registry
        self.artifact_store = artifact_store

    def before_node(
        self,
        *,
        task_id: str,
        graph: ContractualExecutionGraph,
        node: RuntimeNode,
    ) -> List[ContractViolation]:
        contract = self.registry.get(node.contract_name)
        required = graph.required_artifacts_for(node.node_id) + list(node.inputs)
        return check_required_artifacts(
            task_id=task_id,
            node_id=node.node_id,
            contract=contract,
            required_artifacts=required,
            available_artifacts=self.artifact_store.ids(),
        )

    def after_node(
        self,
        *,
        task_id: str,
        node: RuntimeNode,
        output: Dict[str, Any],
        observed: Dict[str, int],
    ) -> List[ContractViolation]:
        contract = self.registry.get(node.contract_name)
        violations = validate_schema(
            task_id=task_id,
            node_id=node.node_id,
            contract=contract,
            payload=output,
            direction="output",
        )
        violations.extend(
            check_budget(
                task_id=task_id,
                node_id=node.node_id,
                contract=contract,
                observed=observed,
            )
        )
        return violations
