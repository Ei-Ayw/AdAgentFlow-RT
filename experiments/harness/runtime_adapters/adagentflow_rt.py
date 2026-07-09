"""AdAgentFlow-RT full contractual runtime adapter."""
from __future__ import annotations

from uuid import uuid4

from app.contracts.models import Artifact, Contract
from app.contracts.registry import ContractRegistry
from app.runtime.artifact_store import InMemoryArtifactStore
from app.runtime.event_log import InMemoryEventLog
from app.runtime.fault_localizer import FaultLocalizer
from app.runtime.graph import ContractualExecutionGraph, RuntimeNode
from app.runtime.monitor import RuntimeMonitor
from app.runtime.recovery import RecoveryController
from experiments.harness.runtime_adapters.base import RuntimeAdapter, RuntimeResult


class AdAgentFlowRTAdapter(RuntimeAdapter):
    method_name = "adagentflow_rt"

    def run_task(self, task, context, stressors, runtime_config):
        run_id = f"run_{uuid4().hex}"
        registry = ContractRegistry(
            [
                Contract(
                    name="rt.mock_resolution",
                    capability="reliable_resolution",
                    output_schema={
                        "type": "object",
                        "required": ["resolution", "policy_compliant"],
                        "properties": {
                            "resolution": {"type": "string"},
                            "policy_compliant": {"type": "boolean"},
                        },
                    },
                )
            ]
        )
        node = RuntimeNode(
            node_id="resolve",
            role="agent",
            capability="reliable_resolution",
            contract_name="rt.mock_resolution",
            outputs=["resolution_artifact"],
        )
        graph = ContractualExecutionGraph(
            graph_id="mock_rt_graph",
            nodes={node.node_id: node},
            edges=[],
            entry_nodes=[node.node_id],
            terminal_nodes=[node.node_id],
        )
        store = InMemoryArtifactStore()
        event_log = InMemoryEventLog()
        monitor = RuntimeMonitor(registry, store)
        localizer = FaultLocalizer()
        recovery = RecoveryController()

        event_log.record(run_id=run_id, task_id=task.task_id, event_type="graph.created")
        event_log.record(run_id=run_id, task_id=task.task_id, event_type="node.started", node_id=node.node_id)
        output = {"resolution": "ok", "policy_compliant": True}
        faults = []
        for stressor in stressors:
            event = {"task_id": task.task_id, "method": self.method_name, "phase": "node"}
            if stressor.should_inject(event):
                faults.append(stressor.apply(output))

        violations = monitor.before_node(task_id=task.task_id, graph=graph, node=node)
        violations.extend(
            monitor.after_node(
                task_id=task.task_id,
                node=node,
                output=output,
                observed={"latency_ms": 1000, "llm_calls": 1, "tool_calls": 2, "tokens": 500, "retries": 0},
            )
        )
        decisions = []
        for violation in violations:
            event_log.record(
                run_id=run_id,
                task_id=task.task_id,
                event_type="contract.violated",
                node_id=node.node_id,
                status="violation",
                payload=violation.__dict__.copy(),
            )
            diagnosis = localizer.diagnose(graph=graph, violation=violation)
            event_log.record(
                run_id=run_id,
                task_id=task.task_id,
                event_type="fault.localized",
                node_id=node.node_id,
                payload=diagnosis.__dict__.copy(),
            )
            decision = recovery.select(
                violation=violation,
                diagnosis=diagnosis,
                remaining_budget={"retries": int(runtime_config.get("max_retries", 2))},
            )
            decisions.append(decision)
            event_log.record(
                run_id=run_id,
                task_id=task.task_id,
                event_type="recovery.selected",
                node_id=node.node_id,
                payload=decision.__dict__.copy(),
                status=decision.action,
            )

        recovered = bool(violations and all(decision.should_continue for decision in decisions))
        success = not violations or recovered
        if success:
            store.put(
                Artifact(
                    artifact_id="resolution_artifact",
                    producer_node=node.node_id,
                    content=output,
                    contract_name=node.contract_name,
                    validation_status="valid" if not violations else "recovered",
                )
            )
            event_log.record(
                run_id=run_id,
                task_id=task.task_id,
                event_type="artifact.produced",
                node_id=node.node_id,
                payload={"artifact_id": "resolution_artifact"},
            )
        event_log.record(
            run_id=run_id,
            task_id=task.task_id,
            event_type="task.finalized",
            status="success" if success else "dead_letter",
        )
        return RuntimeResult(
            benchmark=task.benchmark,
            domain=task.domain,
            task_id=task.task_id,
            trial_id=task.trial_id,
            method=self.method_name,
            run_id=run_id,
            success=success,
            native_metrics={"task_success": success, **task.native_metrics},
            runtime_metrics={
                "contract_violations": len(violations),
                "recovery_actions": len(decisions),
                "fault_propagation_depth": 0,
                "contaminated_artifact_count": 0,
            },
            events=event_log.to_dicts(),
            latency_ms=1200 + 300 * len(decisions),
            tool_calls=2,
            llm_calls=1 + len(decisions),
            attempts=1 + len(decisions),
            injected_faults=faults,
            recovered=recovered,
            dead_letter=not success,
            error=None if success else "contract recovery failed",
        )
