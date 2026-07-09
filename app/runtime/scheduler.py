"""In-memory scheduler for DAG execution."""
from __future__ import annotations

from typing import Iterable, List, Set

from app.runtime.artifact_store import InMemoryArtifactStore
from app.runtime.graph import ContractualExecutionGraph, RuntimeNode


class RuntimeScheduler:
    def __init__(self, graph: ContractualExecutionGraph, artifact_store: InMemoryArtifactStore):
        graph.validate_dag()
        self.graph = graph
        self.artifact_store = artifact_store
        self.completed: Set[str] = set()
        self.failed: Set[str] = set()

    def runnable_nodes(self) -> List[RuntimeNode]:
        ready: List[RuntimeNode] = []
        for node_id, node in self.graph.nodes.items():
            if node_id in self.completed or node_id in self.failed:
                continue
            upstream = self.graph.upstream(node_id)
            if all(parent in self.completed for parent in upstream):
                required = self.graph.required_artifacts_for(node_id) + list(node.inputs)
                if all(self.artifact_store.get(artifact_id) for artifact_id in required):
                    ready.append(node)
                elif node_id in self.graph.entry_nodes and not required:
                    ready.append(node)
        return ready

    def mark_completed(self, node_id: str) -> None:
        self.completed.add(node_id)

    def mark_failed(self, node_id: str) -> None:
        self.failed.add(node_id)

    def is_finished(self) -> bool:
        terminal_done = all(node_id in self.completed for node_id in self.graph.terminal_nodes)
        no_more_work = not self.runnable_nodes()
        return terminal_done or no_more_work

    def remaining(self) -> Iterable[str]:
        return set(self.graph.nodes) - self.completed - self.failed
