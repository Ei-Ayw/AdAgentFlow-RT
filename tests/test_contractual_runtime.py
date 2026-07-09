from __future__ import annotations

from app.contracts.models import Artifact, Contract
from app.contracts.registry import ContractRegistry
from app.runtime.artifact_store import InMemoryArtifactStore
from app.runtime.fault_localizer import FaultLocalizer
from app.runtime.graph import RuntimeNode
from app.runtime.monitor import RuntimeMonitor
from app.runtime.planner import sequential_graph
from app.runtime.replay import replay_trace, summarize_events
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


def test_replay_trace_accepts_runtime_events_and_extracts_recovery_chain():
    from app.runtime.event_log import InMemoryEventLog

    log = InMemoryEventLog()
    for event_type in (
        "graph.created",
        "contract.loaded",
        "node.started",
        "contract.checked",
        "contract.violated",
        "fault.localized",
        "recovery.selected",
        "recovery.succeeded",
        "task.finalized",
    ):
        payload = {"action": "quick_repair"} if event_type.startswith("recovery.") else {}
        log.record(
            run_id="run_1",
            task_id="task_1",
            event_type=event_type,
            node_id="n1",
            status="quick_repair" if event_type.startswith("recovery.") else "ok",
            payload=payload,
        )

    diagnostic = replay_trace(log.events)
    summary = summarize_events(log.events)

    assert diagnostic.replayable is True
    assert diagnostic.has_recovery_chain is True
    assert diagnostic.recovery_actions == ["quick_repair", "quick_repair"]
    assert diagnostic.terminal_status == "ok"
    assert summary["replayable"] is True
    assert summary["by_type"]["contract.violated"] == 1


def test_replay_trace_reports_missing_order_and_mixed_run_errors():
    events = [
        {
            "run_id": "run_2",
            "task_id": "task_2",
            "event_type": "task.finalized",
            "status": "success",
            "created_at": "2026-01-01T00:00:00+00:00",
            "payload": {},
        },
        {
            "run_id": "run_1",
            "task_id": "task_1",
            "event_type": "graph.created",
            "status": "ok",
            "created_at": "2026-01-01T00:00:01+00:00",
            "payload": {},
        },
    ]

    diagnostic = replay_trace(events)

    assert diagnostic.replayable is False
    assert "contract.loaded" in diagnostic.missing_required_events
    assert "node.started" in diagnostic.missing_required_events
    assert "contract.checked" in diagnostic.missing_required_events
    assert "task.finalized appears before graph.created" in diagnostic.ordering_errors
    assert any("multiple task_ids" in error for error in diagnostic.ordering_errors)
    assert any("multiple run_ids" in error for error in diagnostic.ordering_errors)
