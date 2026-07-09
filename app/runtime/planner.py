"""Graph planning helpers."""
from __future__ import annotations

from typing import Dict, List

from app.runtime.graph import ContractualExecutionGraph, RuntimeEdge, RuntimeNode


def sequential_graph(
    *,
    graph_id: str,
    steps: List[RuntimeNode],
    artifact_prefix: str = "artifact",
) -> ContractualExecutionGraph:
    if not steps:
        raise ValueError("steps must not be empty")
    nodes: Dict[str, RuntimeNode] = {step.node_id: step for step in steps}
    edges: List[RuntimeEdge] = []
    for idx in range(len(steps) - 1):
        artifact_id = f"{artifact_prefix}_{steps[idx].node_id}"
        steps[idx].outputs.append(artifact_id)
        steps[idx + 1].inputs.append(artifact_id)
        edges.append(
            RuntimeEdge(
                source=steps[idx].node_id,
                target=steps[idx + 1].node_id,
                artifact=artifact_id,
            )
        )
    return ContractualExecutionGraph(
        graph_id=graph_id,
        nodes=nodes,
        edges=edges,
        entry_nodes=[steps[0].node_id],
        terminal_nodes=[steps[-1].node_id],
    )
