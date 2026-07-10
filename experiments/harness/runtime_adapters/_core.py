"""Shared runtime adapter helpers for LLM-backed runs."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from app.contracts.models import Artifact, Contract, ContractViolation, ResourceBudget
from app.contracts.registry import ContractRegistry
from app.runtime.artifact_store import InMemoryArtifactStore
from app.runtime.fault_localizer import FaultLocalizer
from app.runtime.graph import RuntimeNode
from app.runtime.monitor import RuntimeMonitor
from app.runtime.planner import sequential_graph
from app.runtime.recovery import RecoveryController
from app.runtime.scheduler import RuntimeScheduler
from experiments.harness.external_data import evaluate_external
from experiments.harness.fault_plans import planned_faults_for
from experiments.harness.llm import LLMCallStats, SyncLLMClient
from experiments.harness.runtime_adapters.base import RuntimeResult
from experiments.harness.scenarios import ScenarioTask, evaluate_native


SCHEMA_HINT = {
    "type": "object",
    "required": ["resolution", "policy_compliant"],
    "properties": {
        "resolution": {"type": "string"},
        "policy_compliant": {"type": "boolean"},
    },
}

TOOL_SCHEMA = {
    "type": "object",
    "required": ["tool", "status"],
    "properties": {
        "tool": {"type": "string"},
        "status": {"type": "string"},
    },
}


def _prompt_for_task(task_payload: Dict[str, Any]) -> Tuple[str, str]:
    customer_goal = task_payload.get("customer_goal", "")
    tools = task_payload.get("tools") or []
    policy_text = task_payload.get("policy_text") or ""
    goal_change = bool(task_payload.get("goal_change"))
    change_target = task_payload.get("change_target_goal") or ""
    nl_assertions = task_payload.get("nl_assertions") or []

    system_parts = [
        "You are a customer-service agent. Resolve the customer's request using the "
        "available tools. Always return JSON with keys: "
        '"resolution" (string) and "policy_compliant" (boolean).'
    ]
    if policy_text:
        system_parts.append("You MUST follow this domain policy strictly:\n" + policy_text)
    system = "\n\n".join(system_parts)

    user_parts = [
        f"Available tools: {list(tools)[:20]}",
        f"Customer goal: {customer_goal}",
    ]
    if goal_change and change_target:
        user_parts.append(
            "IMPORTANT: the customer will change their goal mid-conversation. "
            f"Be ready to switch to: {change_target}"
        )
    if nl_assertions:
        user_parts.append(
            "Evaluation criteria your response should satisfy: "
            + "; ".join(str(a) for a in nl_assertions[:3])
        )
    user_parts.append(
        'Respond strictly as JSON: {"resolution": "...", "policy_compliant": true|false}'
    )
    return system, "\n".join(user_parts)


def _extract_tools_from_text(text: str, candidate_tools: List[str]) -> List[str]:
    if not text:
        return []
    text_lc = text.lower()
    return [tool for tool in candidate_tools if tool.lower() in text_lc]


def _infer_policy_flag(text: str) -> bool:
    text_lc = (text or "").lower()
    if any(token in text_lc for token in ("cannot", "decline", "not allowed", "policy violation")):
        return False
    return any(token in text_lc for token in ("completed", "resolved", "per policy", "policy"))


def _detect_violations(parsed: Optional[Dict[str, Any]], raw_text: str) -> List[Dict[str, Any]]:
    violations: List[Dict[str, Any]] = []
    if parsed is None:
        violations.append({"type": "SCHEMA_VIOLATION", "message": "llm output is not valid JSON", "severity": "high"})
        return violations
    if not isinstance(parsed, dict):
        violations.append({"type": "SCHEMA_VIOLATION", "message": "parsed output is not an object", "severity": "high"})
        return violations
    if "resolution" not in parsed or "policy_compliant" not in parsed:
        violations.append({"type": "SCHEMA_VIOLATION", "message": "missing required keys", "severity": "high"})
    if "policyCompliant" in parsed and "policy_compliant" not in parsed:
        violations.append({"type": "SCHEMA_VIOLATION", "message": "key naming drift (policyCompliant)", "severity": "low"})
    if parsed.get("policy_compliant") is True and "i am not sure" in (parsed.get("resolution") or "").lower():
        violations.append({"type": "SEMANTIC_DRIFT", "message": "policy_compliant true but resolution expresses uncertainty", "severity": "medium"})
    if parsed.get("policy_compliant") is False and "completed" in (parsed.get("resolution") or "").lower():
        violations.append({"type": "SEMANTIC_DRIFT", "message": "policy_compliant false but resolution says completed", "severity": "medium"})
    return violations


def _stats_sum(stats: List[LLMCallStats]) -> Dict[str, float]:
    return {
        "input_tokens": sum(s.input_tokens for s in stats),
        "output_tokens": sum(s.output_tokens for s in stats),
        "latency_ms": sum(s.latency_ms for s in stats),
        "cost_estimate": round(sum(s.cost_estimate for s in stats), 6),
    }


def _payload_to_scenario(payload: Dict[str, Any]) -> ScenarioTask:
    return ScenarioTask(
        task_id="",
        domain=str(payload.get("domain", "")),
        benchmark="",
        customer_goal=str(payload.get("customer_goal", "")),
        expected_resolution=str(payload.get("expected_resolution", "")),
        expected_policy_compliant=bool(payload.get("expected_policy_compliant", True)),
        tools=tuple(payload.get("tools") or ()),
        difficulty=str(payload.get("difficulty", "smoke")),
        goal_change=bool(payload.get("goal_change", False)),
        change_target_goal=str(payload.get("change_target_goal", "")),
        expected_tool_sequence=tuple(payload.get("expected_tool_sequence") or ()),
    )


def _payload_to_external_task(payload: Dict[str, Any]):
    from experiments.harness.external_data import ExternalTask

    return ExternalTask(
        benchmark=str(payload.get("_benchmark", "tau3")),
        domain=str(payload.get("domain", "")),
        task_id=str(payload.get("_task_id", "")),
        customer_goal=str(payload.get("customer_goal", "")),
        policy_text=str(payload.get("policy_text", "")),
        available_tools=tuple(payload.get("tools") or ()),
        expected_tool_sequence=tuple(payload.get("expected_tool_sequence") or ()),
        expected_policy_compliant=bool(payload.get("expected_policy_compliant", True)),
        goal_change=bool(payload.get("goal_change", False)),
        change_target_goal=str(payload.get("change_target_goal", "")),
        nl_assertions=tuple(payload.get("nl_assertions") or ()),
        evaluation_basis=str(payload.get("evaluation_basis", "NL_ASSERTIONS")),
        raw={},
    )


def _build_runtime_result(
    *,
    task: Any,
    method: str,
    run_id: str,
    success: bool,
    native: Dict[str, Any],
    llm_stats: List[LLMCallStats],
    tool_sequence: List[str],
    injected_faults: List[Dict[str, Any]],
    attempts: int,
    recovered: bool,
    dead_letter: bool,
    ablation: Optional[str],
    events: List[Dict[str, Any]],
    contract_violations: int,
    recovery_actions: int,
    bounded_recovery_actions: int = 0,
    error: Optional[str] = None,
) -> RuntimeResult:
    s = _stats_sum(llm_stats)
    return RuntimeResult(
        benchmark=task.benchmark,
        domain=task.domain,
        task_id=task.task_id,
        trial_id=task.trial_id,
        method=method,
        run_id=run_id,
        success=success,
        ablation=ablation,
        benchmark_adapter_mode=task.adapter_mode,
        external_command=task.external_command,
        native_metrics={**task.native_metrics, **native},
        runtime_metrics={
            "contract_violations": contract_violations,
            "recovery_actions": recovery_actions,
            "bounded_recovery_actions": bounded_recovery_actions,
            "input_tokens": s["input_tokens"],
            "output_tokens": s["output_tokens"],
            "llm_cost_estimate": s["cost_estimate"],
        },
        events=events,
        latency_ms=s["latency_ms"] + 200 * len(tool_sequence),
        tool_calls=len(tool_sequence),
        llm_calls=len(llm_stats),
        attempts=attempts,
        injected_faults=injected_faults,
        recovered=recovered,
        dead_letter=dead_letter,
        error=error,
    )


def _normalize_result_payload(raw_text: str, parsed: Optional[Dict[str, Any]]) -> Tuple[str, Optional[Dict[str, Any]]]:
    if isinstance(parsed, dict):
        candidate = dict(parsed)
    else:
        candidate = {"resolution": raw_text.strip(), "policy_compliant": _infer_policy_flag(raw_text)}
    if "policyCompliant" in candidate and "policy_compliant" not in candidate:
        candidate["policy_compliant"] = candidate.pop("policyCompliant")
    if "resolution" not in candidate and "content" in candidate:
        candidate["resolution"] = str(candidate.get("content") or "")
    if "policy_compliant" not in candidate:
        candidate["policy_compliant"] = _infer_policy_flag(str(candidate.get("resolution") or raw_text))
    if "resolution" not in candidate:
        candidate["resolution"] = str(raw_text or "")
    normalized = {
        "resolution": str(candidate.get("resolution") or ""),
        "policy_compliant": bool(candidate.get("policy_compliant")),
    }
    return json.dumps(normalized, ensure_ascii=False), normalized


def _apply_planned_faults(
    *,
    task: Any,
    method: str,
    phase: str,
    attempt: int,
    raw_text: str,
    parsed: Optional[Dict[str, Any]],
    stressors: List[Any],
    fault_plan: List[Dict[str, Any]],
    injected: List[Dict[str, Any]],
    log_event,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    response_obj = dict(parsed) if isinstance(parsed, dict) else {"content": raw_text}
    if "content" not in response_obj:
        response_obj["content"] = raw_text
    for stressor in stressors:
        for entry in planned_faults_for(
            fault_plan=fault_plan,
            stressor_name=stressor.name,
            phase=phase,
            attempt=attempt,
        ):
            fault = stressor.apply(response_obj)
            fault.update(
                {
                    "task_id": task.task_id,
                    "method": method,
                    "phase": phase,
                    "attempt": attempt,
                    "injection_point": entry.injection_point,
                    "fault_seed": entry.fault_seed,
                }
            )
            injected.append(fault)
            log_event("fault.injected", **{k: fault[k] for k in ("stressor", "attempt", "injection_point", "fault_seed")})
    body = {k: v for k, v in response_obj.items() if k != "content"}
    if body:
        return json.dumps(body, ensure_ascii=False), body
    return str(response_obj.get("content") or raw_text), None


def _quick_repair_payload(payload: Dict[str, Any], *, schema_type: str) -> Dict[str, Any]:
    repaired = dict(payload)
    if schema_type == "tool":
        if "tool" not in repaired:
            repaired["tool"] = str(repaired.get("drifted_tool") or repaired.get("content") or "tool")
        if "status" not in repaired:
            repaired["status"] = "ok"
        return {"tool": str(repaired["tool"]), "status": str(repaired["status"])}
    _, normalized = _normalize_result_payload(str(repaired.get("content") or ""), repaired)
    return normalized or {"resolution": "", "policy_compliant": False}


def _evaluate_native_metrics(*, task_payload: Dict[str, Any], raw_text: str, tool_sequence: List[str]) -> Dict[str, Any]:
    scenario = _payload_to_scenario(task_payload)
    if task_payload.get("adapter_mode") == "external" or task_payload.get("policy_text"):
        return evaluate_external(
            task=_payload_to_external_task(task_payload),
            generated_text=raw_text,
            tool_sequence=tool_sequence,
        )
    return evaluate_native(
        task=scenario,
        generated_text=raw_text,
        generated_actions=[],
        tool_sequence=tool_sequence,
    )


def _final_contract_satisfied(parsed: Optional[Dict[str, Any]]) -> bool:
    return isinstance(parsed, dict) and {"resolution", "policy_compliant"}.issubset(parsed)


def _evaluate_with_runtime_kernel(
    *,
    task: Any,
    seed: int,
    stressors: List[Any],
    runtime_config: Dict[str, Any],
    context: Dict[str, Any],
) -> RuntimeResult:
    run_id = f"run_{uuid4().hex}"
    ablation = runtime_config.get("ablation")
    task_payload = task.payload or {}
    system, user = _prompt_for_task(task_payload)
    candidate_tools = list(task_payload.get("expected_tool_sequence") or task_payload.get("tools") or ["lookup"])
    candidate_tools = candidate_tools[: max(1, min(3, len(candidate_tools)))]
    max_retries = int(runtime_config.get("max_retries", 2))
    use_localizer = ablation != "without_fault_localizer"
    use_monitor = ablation != "without_contract_monitor"
    use_recovery = ablation != "without_bounded_recovery"
    use_event_trace = ablation != "without_event_trace"

    client = SyncLLMClient(method="adagentflow_rt", seed=seed)
    llm_stats: List[LLMCallStats] = []
    events: List[Dict[str, Any]] = []
    injected: List[Dict[str, Any]] = []
    tool_sequence: List[str] = []
    contract_violations = 0
    recovery_actions = 0
    bounded_recovery_actions = 0
    attempts = 0
    resolve_attempts = 0
    recovered = False
    error: Optional[str] = None
    raw_text = ""
    parsed: Optional[Dict[str, Any]] = None

    def _log_event(event_type: str, **payload: Any) -> None:
        if use_event_trace:
            events.append({"event_type": event_type, "payload": payload})

    steps = [
        RuntimeNode(node_id=f"tool_{idx}", role="tool", capability=tool, contract_name=f"tool.contract.{idx}")
        for idx, tool in enumerate(candidate_tools)
    ]
    steps.append(RuntimeNode(node_id="resolve", role="agent", capability="resolve", contract_name="resolve.contract"))
    graph = sequential_graph(graph_id=f"graph_{task.task_id}", steps=steps, artifact_prefix=f"artifact_{task.task_id}")
    registry = ContractRegistry(
        [
            *(Contract(
                name=f"tool.contract.{idx}",
                capability=tool,
                output_schema=TOOL_SCHEMA,
                resource_budget=ResourceBudget(max_tool_calls=1, max_retries=max_retries),
            ) for idx, tool in enumerate(candidate_tools)),
            Contract(
                name="resolve.contract",
                capability="resolve",
                output_schema=SCHEMA_HINT,
                resource_budget=ResourceBudget(max_llm_calls=max_retries + 2, max_retries=max_retries, max_tokens=4096),
            ),
        ]
    )
    store = InMemoryArtifactStore()
    scheduler = RuntimeScheduler(graph, store)
    monitor = RuntimeMonitor(registry, store)
    localizer = FaultLocalizer()
    recovery = RecoveryController()
    remaining_budget = {"retries": max_retries, "recovery_steps": max_retries + 1}
    fault_plan = list(context.get("fault_plan") or [])

    _log_event("graph.created", graph_id=graph.graph_id)
    _log_event("contract.loaded", contracts=registry.names())

    while not scheduler.is_finished():
        runnable = scheduler.runnable_nodes()
        if not runnable:
            error = "runtime stalled before terminal node"
            break
        node = runnable[0]
        attempts += 1
        _log_event("node.started", node_id=node.node_id, attempt=attempts)
        if use_monitor:
            pre = monitor.before_node(task_id=task.task_id, graph=graph, node=node)
            for violation in pre:
                contract_violations += 1
                _log_event("contract.violated", node_id=node.node_id, violation_type=violation.violation_type, message=violation.message)
            if pre:
                error = pre[0].message
                scheduler.mark_failed(node.node_id)
                break

        if node.node_id != "resolve":
            output = {"tool": node.capability, "status": "ok"}
            tool_sequence.append(node.capability)
            node_raw = json.dumps(output, ensure_ascii=False)
            node_parsed = output
        else:
            result = client.chat(system=system, user=user, schema_hint=SCHEMA_HINT)
            llm_stats.append(result.stats)
            raw_text = result.content
            parsed = result.parsed if result.error is None else None
            resolve_attempts += 1
            node_raw, node_parsed = _apply_planned_faults(
                task=task,
                method="adagentflow_rt",
                phase="node",
                attempt=resolve_attempts,
                raw_text=raw_text,
                parsed=parsed,
                stressors=stressors,
                fault_plan=fault_plan,
                injected=injected,
                log_event=_log_event,
            )
            raw_text, parsed = node_raw, node_parsed
            output = node_parsed or {}

        violations: List[ContractViolation] = []
        if use_monitor:
            violations = monitor.after_node(
                task_id=task.task_id,
                node=node,
                output=output,
                observed={
                    "llm_calls": len(llm_stats) if node.node_id == "resolve" else 0,
                    "tool_calls": 0 if node.node_id == "resolve" else 1,
                    "tokens": sum(s.output_tokens for s in llm_stats) if node.node_id == "resolve" else 0,
                },
            )
        else:
            violations = []

        if violations:
            for violation in violations:
                contract_violations += 1
                _log_event("contract.violated", node_id=node.node_id, violation_type=violation.violation_type, message=violation.message)
                diagnosis = localizer.diagnose(graph=graph, violation=violation) if use_localizer else None
                if diagnosis is not None:
                    _log_event("fault.localized", node_id=diagnosis.responsible_node, fault_class=diagnosis.fault_class)
                decision = recovery.select(
                    violation=violation,
                    diagnosis=diagnosis or localizer.diagnose(graph=graph, violation=violation),
                    remaining_budget=remaining_budget,
                ) if use_recovery else None
                if decision is None:
                    error = violation.message
                    scheduler.mark_failed(node.node_id)
                    break
                recovery_actions += 1
                bounded_recovery_actions += 1
                _log_event("recovery.selected", action=decision.action, node_id=node.node_id, reason=decision.reason)
                _log_event("recovery.attempted", action=decision.action, node_id=node.node_id)
                if decision.action == "quick_repair":
                    repaired = _quick_repair_payload(output or {"content": node_raw}, schema_type="tool" if node.node_id != "resolve" else "resolve")
                    retry_violations = monitor.after_node(
                        task_id=task.task_id,
                        node=node,
                        output=repaired,
                        observed={
                            "llm_calls": len(llm_stats) if node.node_id == "resolve" else 0,
                            "tool_calls": 0 if node.node_id == "resolve" else 1,
                            "tokens": sum(s.output_tokens for s in llm_stats) if node.node_id == "resolve" else 0,
                        },
                    ) if use_monitor else []
                    if retry_violations:
                        _log_event("recovery.failed", action=decision.action, node_id=node.node_id)
                        error = retry_violations[0].message
                        scheduler.mark_failed(node.node_id)
                        break
                    output = repaired
                elif decision.action in {"retry_same_agent", "reroute_agent", "rollback_to_checkpoint"} and remaining_budget["retries"] > 0:
                    remaining_budget["retries"] -= 1
                    if node.node_id == "resolve":
                        retry = client.chat(
                            system=system + "\n\nPrevious attempt violated the runtime contract. Return corrected JSON only.",
                            user=user,
                            schema_hint=SCHEMA_HINT,
                        )
                        llm_stats.append(retry.stats)
                        resolve_attempts += 1
                        raw_text, parsed = _apply_planned_faults(
                            task=task,
                            method="adagentflow_rt",
                            phase="node",
                            attempt=resolve_attempts,
                            raw_text=retry.content,
                            parsed=retry.parsed if retry.error is None else None,
                            stressors=stressors,
                            fault_plan=fault_plan,
                            injected=injected,
                            log_event=_log_event,
                        )
                        output = parsed or {}
                    else:
                        output = {"tool": node.capability, "status": "ok"}
                    retry_violations = monitor.after_node(
                        task_id=task.task_id,
                        node=node,
                        output=output,
                        observed={
                            "llm_calls": len(llm_stats) if node.node_id == "resolve" else 0,
                            "tool_calls": 0 if node.node_id == "resolve" else 1,
                            "tokens": sum(s.output_tokens for s in llm_stats) if node.node_id == "resolve" else 0,
                        },
                    ) if use_monitor else []
                    if retry_violations:
                        _log_event("recovery.failed", action=decision.action, node_id=node.node_id)
                        error = retry_violations[0].message
                        scheduler.mark_failed(node.node_id)
                        break
                else:
                    _log_event("recovery.failed", action=decision.action, node_id=node.node_id)
                    error = f"terminal recovery action: {decision.action}"
                    scheduler.mark_failed(node.node_id)
                    break
                recovered = True
                _log_event("recovery.succeeded", action=decision.action, node_id=node.node_id)
            if node.node_id in scheduler.failed:
                break

        artifact = Artifact(
            artifact_id=node.outputs[0] if node.outputs else f"artifact_{node.node_id}",
            producer_node=node.node_id,
            content=output,
            contract_name=node.contract_name,
            validation_status="valid",
        )
        store.put(artifact)
        scheduler.mark_completed(node.node_id)
        if node.node_id == "resolve":
            if use_monitor:
                raw_text, parsed = _normalize_result_payload(raw_text or node_raw, output if isinstance(output, dict) else None)
            else:
                raw_text, parsed = node_raw, node_parsed

    native = _evaluate_native_metrics(task_payload=task_payload, raw_text=raw_text, tool_sequence=tool_sequence)
    success_native = bool(native.get("task_success"))
    dead_letter = (not success_native) or (not _final_contract_satisfied(parsed)) or bool(error)
    success = bool(success_native and not dead_letter)
    if recovered and success:
        _log_event("recovery.succeeded", action="finalized", node_id="resolve")
    elif recovery_actions:
        _log_event("recovery.failed", action="finalized", node_id="resolve")
    _log_event("task.finalized", success=success, dead_letter=dead_letter)
    if dead_letter and error is None:
        error = "contract recovery failed"
    assert not (success and dead_letter)
    return _build_runtime_result(
        task=task,
        method="adagentflow_rt",
        run_id=run_id,
        success=success,
        native=native,
        llm_stats=llm_stats,
        tool_sequence=tool_sequence,
        injected_faults=injected,
        attempts=attempts,
        recovered=bool(recovered and success),
        dead_letter=dead_letter,
        ablation=ablation,
        events=events,
        contract_violations=contract_violations,
        recovery_actions=recovery_actions,
        bounded_recovery_actions=bounded_recovery_actions,
        error=error,
    )


def evaluate_task(
    *,
    task: Any,
    method: str,
    seed: int,
    context: Optional[Dict[str, Any]] = None,
    stressors: List[Any],
    runtime_config: Dict[str, Any],
) -> RuntimeResult:
    if method == "adagentflow_rt":
        return _evaluate_with_runtime_kernel(
            task=task,
            seed=seed,
            stressors=stressors,
            runtime_config=runtime_config,
            context=context or {},
        )

    run_id = f"run_{uuid4().hex}"
    ablation = runtime_config.get("ablation")
    task_payload = task.payload or {}
    candidate_tools = list(task_payload.get("tools") or ["lookup", "act", "respond"])
    system, user = _prompt_for_task(task_payload)
    fault_plan = list((context or {}).get("fault_plan") or [])
    injected: List[Dict[str, Any]] = []
    llm_stats: List[LLMCallStats] = []
    tool_sequence: List[str] = []
    events: List[Dict[str, Any]] = []
    contract_violations = 0
    recovery_actions = 0
    bounded_recovery_actions = 0
    attempts = 0
    parsed: Optional[Dict[str, Any]] = None
    raw_text = ""
    error: Optional[str] = None
    use_schema_check = method == "schema_only"
    max_retries = 0 if method == "vanilla" else int(runtime_config.get("max_retries", 2))
    client = SyncLLMClient(method=method, seed=seed)

    def _log_event(event_type: str, **payload: Any) -> None:
        if method == "schema_only":
            events.append({"event_type": event_type, "payload": payload})

    max_loops = max(1, max_retries + 1)
    for loop_idx in range(max_loops):
        attempts += 1
        result = client.chat(system=system, user=user, schema_hint=SCHEMA_HINT)
        llm_stats.append(result.stats)
        raw_text = result.content
        parsed = result.parsed if result.error is None else None
        raw_text, parsed = _apply_planned_faults(
            task=task,
            method=method,
            phase="node",
            attempt=attempts,
            raw_text=raw_text,
            parsed=parsed,
            stressors=stressors,
            fault_plan=fault_plan,
            injected=injected,
            log_event=_log_event,
        )
        violations = _detect_violations(parsed, raw_text) if use_schema_check else []
        contract_violations += len(violations)
        if use_schema_check and any(v["type"] == "SCHEMA_VIOLATION" for v in violations):
            repair = client.chat(
                system="You fix JSON output to match the schema exactly.",
                user=raw_text + '\n\nReturn only valid JSON: {"resolution": "...", "policy_compliant": true|false}',
                schema_hint=SCHEMA_HINT,
            )
            llm_stats.append(repair.stats)
            raw_text, parsed = _normalize_result_payload(repair.content, repair.parsed if repair.error is None else None)
            recovery_actions += 1
            _log_event("recovery.attempted", action="quick_repair")
        if method == "retry_only" and parsed is None and loop_idx < max_loops - 1:
            continue
        break

    if method == "vanilla" and parsed is None:
        second = client.chat(system="Answer the customer request in plain text.", user=user)
        llm_stats.append(second.stats)
        raw_text = second.content

    tool_sequence = _extract_tools_from_text(raw_text, candidate_tools)
    native = _evaluate_native_metrics(task_payload=task_payload, raw_text=raw_text, tool_sequence=tool_sequence)
    success_native = bool(native.get("task_success"))
    dead_letter = not success_native
    success = bool(success_native and not dead_letter)
    if dead_letter:
        error = "contract recovery failed" if method != "vanilla" else "vanilla: off-policy / json failure"
    assert not (success and dead_letter)
    return _build_runtime_result(
        task=task,
        method=method,
        run_id=run_id,
        success=success,
        native=native,
        llm_stats=llm_stats,
        tool_sequence=tool_sequence,
        injected_faults=injected,
        attempts=attempts,
        recovered=False,
        dead_letter=dead_letter,
        ablation=ablation,
        events=events,
        contract_violations=contract_violations,
        recovery_actions=recovery_actions,
        bounded_recovery_actions=bounded_recovery_actions,
        error=error,
    )
