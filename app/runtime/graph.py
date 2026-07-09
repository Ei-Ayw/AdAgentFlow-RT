"""Contractual execution graph primitives."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class RuntimeNode:
    node_id: str
    role: str
    capability: str
    contract_name: str
    agent_provider: Optional[str] = None
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)


@dataclass
class RuntimeEdge:
    source: str
    target: str
    artifact: str
    dependency_type: str = "required"


@dataclass
class ContractualExecutionGraph:
    graph_id: str
    nodes: Dict[str, RuntimeNode]
    edges: List[RuntimeEdge]
    entry_nodes: List[str]
    terminal_nodes: List[str]

    def downstream(self, node_id: str) -> List[str]:
        return [edge.target for edge in self.edges if edge.source == node_id]

    def upstream(self, node_id: str) -> List[str]:
        return [edge.source for edge in self.edges if edge.target == node_id]

    def required_artifacts_for(self, node_id: str) -> List[str]:
        return [
            edge.artifact
            for edge in self.edges
            if edge.target == node_id and edge.dependency_type == "required"
        ]

    def validate_dag(self) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise ValueError(f"cycle detected at node {node_id}")
            if node_id in visited:
                return
            if node_id not in self.nodes:
                raise ValueError(f"edge references unknown node {node_id}")
            visiting.add(node_id)
            for target in self.downstream(node_id):
                visit(target)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in self.nodes:
            visit(node_id)
