"""AdAgentFlow-RT full contractual runtime adapter."""
from __future__ import annotations

from uuid import uuid4

from app.contracts.models import Artifact, Contract
from app.contracts.registry import ContractRegistry
from app.runtime.artifact_store import InMemoryArtifactStore
from app.runtime.event_log import InMemoryEventLog
from app.runtime.fault_localizer import FaultLocalizer
from app.runtime.graph import ContractualExecutionGraph, RuntimeEdge, RuntimeNode
from app.runtime.monitor import RuntimeMonitor
from app.runtime.recovery import RecoveryController
from experiments.harness.runtime_adapters.base import RuntimeAdapter, RuntimeResult


class AdAgentFlowRTAdapter(RuntimeAdapter):
    method_name = "adagentflow_rt"

    def run_task(self, task, context, stressors, runtime_config):
        run_id = f"run_{uuid4().hex}"
        ablation = runtime_config.get("ablation")
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
        verify_node = RuntimeNode(
            node_id="verify",
            role="verifier",
            capability="policy_verification",
            contract_name="rt.mock_resolution",
            inputs=["resolution_artifact"],
            outputs=["verified_resolution_artifact"],
        )
        finalize_node = RuntimeNode(
            node_id="finalize",
            role="runtime",
            capability="finalize_response",
            contract_name="rt.mock_resolution",
            inputs=["verified_resolution_artifact"],
        )
        graph = ContractualExecutionGraph(
            graph_id="mock_rt_graph",
            nodes={
                node.node_id: node,
                verify_node.node_id: verify_node,
                finalize_node.node_id: finalize_node,
            },
            edges=[
                RuntimeEdge(source="resolve", target="verify", artifact="resolution_artifact"),
                RuntimeEdge(source="verify", target="finalize", artifact="verified_resolution_artifact"),
            ],
            entry_nodes=[node.node_id],
            terminal_nodes=[finalize_node.node_id],
        )
        store = InMemoryArtifactStore()
        event_log = InMemoryEventLog()
        monitor = RuntimeMonitor(registry, store)
        localizer = FaultLocalizer()
        recovery = RecoveryController()

        trace_enabled = ablation != "without_event_trace"
        if trace_enabled:
            event_log.record(
                run_id=run_id,
                task_id=task.task_id,
                event_type="graph.created",
                payload={"graph_id": graph.graph_id, "node_count": len(graph.nodes), "relative_ms": 0},
            )
            event_log.record(
                run_id=run_id,
                task_id=task.task_id,
                event_type="contract.loaded",
                node_id=node.node_id,
                payload={"contract_name": node.contract_name, "relative_ms": 5},
            )
            event_log.record(
                run_id=run_id,
                task_id=task.task_id,
                event_type="node.started",
                node_id=node.node_id,
                payload={"relative_ms": 10},
            )
        output = {"resolution": "ok", "policy_compliant": True}
        faults = []
        for stressor in stressors:
            event = {"task_id": task.task_id, "method": self.method_name, "phase": "node"}
            if stressor.should_inject(event):
                faults.append(stressor.apply(output))
                if trace_enabled:
                    event_log.record(
                        run_id=run_id,
                        task_id=task.task_id,
                        event_type="fault.injected",
                        node_id=node.node_id,
                        status=stressor.name,
                        payload={"stressor": stressor.name, "relative_ms": 100},
                    )

        violations = []
        if ablation != "without_contract_monitor":
            if trace_enabled:
                event_log.record(
                    run_id=run_id,
                    task_id=task.task_id,
                    event_type="contract.checked",
                    node_id=node.node_id,
                    payload={"phase": "before_node", "relative_ms": 900},
                )
            violations = monitor.before_node(task_id=task.task_id, graph=graph, node=node)
            violations.extend(
                monitor.after_node(
                    task_id=task.task_id,
                    node=node,
                    output=output,
                    observed={"latency_ms": 1000, "llm_calls": 1, "tool_calls": 2, "tokens": 500, "retries": 0},
                )
            )
            if trace_enabled:
                event_log.record(
                    run_id=run_id,
                    task_id=task.task_id,
                    event_type="contract.checked",
                    node_id=node.node_id,
                    payload={"phase": "after_node", "relative_ms": 1000},
                )
        decisions = []
        for violation in violations:
            if trace_enabled:
                event_log.record(
                    run_id=run_id,
                    task_id=task.task_id,
                    event_type="contract.violated",
                    node_id=node.node_id,
                    status="violation",
                    payload={**violation.__dict__.copy(), "relative_ms": 1050},
                )
            if ablation == "without_fault_localizer":
                diagnosis = None
            else:
                diagnosis = localizer.diagnose(graph=graph, violation=violation)
                if trace_enabled:
                    event_log.record(
                        run_id=run_id,
                        task_id=task.task_id,
                        event_type="fault.localized",
                        node_id=node.node_id,
                        payload={**diagnosis.__dict__.copy(), "relative_ms": 1100},
                    )
            remaining_budget = {"retries": int(runtime_config.get("max_retries", 2))}
            if ablation == "without_bounded_recovery":
                remaining_budget = {"retries": 999}
            if diagnosis is None:
                decision = _fallback_recovery_decision(violation)
            else:
                decision = recovery.select(
                    violation=violation,
                    diagnosis=diagnosis,
                    remaining_budget=remaining_budget,
                )
            decisions.append(decision)
            if trace_enabled:
                event_log.record(
                    run_id=run_id,
                    task_id=task.task_id,
                    event_type="recovery.started",
                    node_id=node.node_id,
                    status=decision.action,
                    payload={"action": decision.action, "relative_ms": 1150},
                )
            _apply_quick_repair(output, decision.action)
            if trace_enabled:
                event_log.record(
                    run_id=run_id,
                    task_id=task.task_id,
                    event_type="recovery.selected",
                    node_id=node.node_id,
                    payload={**decision.__dict__.copy(), "relative_ms": 1200},
                    status=decision.action,
                )
                event_log.record(
                    run_id=run_id,
                    task_id=task.task_id,
                    event_type="recovery.succeeded" if decision.should_continue else "recovery.failed",
                    node_id=node.node_id,
                    status=decision.action,
                    payload={"action": decision.action, "relative_ms": 1350},
                )

        recovered = bool(violations and all(decision.should_continue for decision in decisions))
        success = not violations or recovered
        native_success = output.get("policy_compliant") is True and "resolution" in output
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
            if trace_enabled:
                event_log.record(
                    run_id=run_id,
                    task_id=task.task_id,
                    event_type="artifact.produced",
                    node_id=node.node_id,
                    payload={"artifact_id": "resolution_artifact", "relative_ms": 1400},
                )
        if trace_enabled:
            if not success:
                event_log.record(
                    run_id=run_id,
                    task_id=task.task_id,
                    event_type="dead_letter.created",
                    node_id=node.node_id,
                    status="dead_letter",
                    payload={"relative_ms": 1450},
                )
            event_log.record(
                run_id=run_id,
                task_id=task.task_id,
                event_type="task.finalized",
                status="success" if success else "dead_letter",
                payload={"relative_ms": 1500},
            )
        trace_metrics = _trace_metrics(event_log.to_dicts())
        return RuntimeResult(
            benchmark=task.benchmark,
            domain=task.domain,
            task_id=task.task_id,
            trial_id=task.trial_id,
            method=self.method_name,
            run_id=run_id,
            success=success,
            ablation=ablation,
            benchmark_adapter_mode=task.adapter_mode,
            external_command=task.external_command,
            native_metrics={**task.native_metrics, "task_success": native_success},
            runtime_metrics={
                "contract_violations": len(violations),
                "recovery_actions": len(decisions),
                "fault_propagation_depth": trace_metrics["fault_propagation_depth"],
                "contaminated_artifact_count": trace_metrics["contaminated_artifact_count"],
                "mean_time_to_detect_ms": trace_metrics["time_to_detect_ms"],
                "mean_time_to_recover_ms": trace_metrics["time_to_recover_ms"],
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


def _apply_quick_repair(output, action: str) -> None:
    if action != "quick_repair":
        return
    if "policyCompliant" in output and "policy_compliant" not in output:
        output["policy_compliant"] = output.pop("policyCompliant")


def _fallback_recovery_decision(violation):
    from app.runtime.recovery import RecoveryDecision

    return RecoveryDecision(
        action="retry_same_agent",
        target_node=violation.node_id,
        reason=f"without_fault_localizer:{violation.violation_type}",
        budget_cost={"retries": 1, "recovery_steps": 1},
        should_continue=True,
    )


def _trace_metrics(events):
    from experiments.harness.metrics.trace_metrics import compute_trace_metrics

    return compute_trace_metrics(events)
