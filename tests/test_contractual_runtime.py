from __future__ import annotations

from app.contracts.models import Artifact, Contract
from app.contracts.registry import ContractRegistry
from app.runtime.artifact_store import InMemoryArtifactStore
from app.runtime.fault_localizer import FaultLocalizer
from app.runtime.graph import RuntimeNode
from app.runtime.monitor import RuntimeMonitor
from app.runtime.planner import sequential_graph
from app.runtime.recovery import RecoveryController
from app.runtime.scheduler import RuntimeScheduler


def test_contract_monitor_detects_schema_violation_and_recovery_decision():
    contract = Contract(
        name="demo.contract",
        capability="demo",
        output_schema={
            "type": "object",
            "required": ["ok"],
            "properties": {"ok": {"type": "boolean"}},
        },
    )
    registry = ContractRegistry([contract])
    store = InMemoryArtifactStore()
    node = RuntimeNode("n1", "agent", "demo", "demo.contract")
    graph = sequential_graph(graph_id="g1", steps=[node])
    monitor = RuntimeMonitor(registry, store)

    violations = monitor.after_node(
        task_id="task_1",
        node=node,
        output={"ok": "yes"},
        observed={"latency_ms": 1, "llm_calls": 1, "tool_calls": 0, "tokens": 1},
    )

    assert len(violations) == 1
    assert violations[0].violation_type == "SCHEMA_VIOLATION"

    diagnosis = FaultLocalizer().diagnose(graph=graph, violation=violations[0])
    decision = RecoveryController().select(
        violation=violations[0],
        diagnosis=diagnosis,
        remaining_budget={"retries": 1},
    )
    assert decision.action in {"quick_repair", "retry_same_agent", "invalidate_downstream"}
    assert decision.should_continue is True


def test_scheduler_runs_after_artifact_dependency_is_available():
    first = RuntimeNode("first", "agent", "produce", "first.contract")
    second = RuntimeNode("second", "agent", "consume", "second.contract")
    graph = sequential_graph(graph_id="g2", steps=[first, second])
    store = InMemoryArtifactStore()
    scheduler = RuntimeScheduler(graph, store)

    assert [node.node_id for node in scheduler.runnable_nodes()] == ["first"]
    scheduler.mark_completed("first")
    assert scheduler.runnable_nodes() == []

    store.put(
        Artifact(
            artifact_id="artifact_first",
            producer_node="first",
            content={"value": 1},
            contract_name="first.contract",
            validation_status="valid",
        )
    )
    assert [node.node_id for node in scheduler.runnable_nodes()] == ["second"]
