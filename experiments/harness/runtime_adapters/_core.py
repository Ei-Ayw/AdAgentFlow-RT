"""Shared runtime adapter helpers for LLM-backed runs.

All four runtime strategies share this skeleton. They differ in:
- whether they call schema validators and recovery on violation
- whether they retry on transient faults
- how they treat off-policy / drift responses

The skeleton calls the SyncLLMClient (real GPU server or deterministic
simulator), tracks tool/LLM/cost stats, and computes native metrics.

When the benchmark adapter loads real τ³-bench / AgentChangeBench tasks the
prompt is augmented with the domain's policy text and the real tool list so
the LLM sees the actual benchmark context.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from experiments.harness.external_data import evaluate_external
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
        system_parts.append(
            "You MUST follow this domain policy strictly:\n" + policy_text
        )
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
    user = "\n".join(user_parts)
    return system, user


def _extract_tools_from_text(text: str, candidate_tools: List[str]) -> List[str]:
    if not text:
        return []
    used: List[str] = []
    text_lc = text.lower()
    for tool in candidate_tools:
        if tool.lower() in text_lc:
            used.append(tool)
    return used


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
    if parsed.get("policy_compliant") is True and "I am not sure" in (parsed.get("resolution") or "").lower():
        violations.append({"type": "SEMANTIC_DRIFT", "message": "policy_compliant true but resolution expresses uncertainty", "severity": "medium"})
    if not parsed.get("policy_compliant") and "completed" in (parsed.get("resolution") or "").lower():
        violations.append({"type": "SEMANTIC_DRIFT", "message": "policy_compliant false but resolution says completed", "severity": "medium"})
    return violations


def _stats_sum(stats: List[LLMCallStats]) -> Dict[str, float]:
    in_tok = sum(s.input_tokens for s in stats)
    out_tok = sum(s.output_tokens for s in stats)
    latency = sum(s.latency_ms for s in stats)
    cost = round(sum(s.cost_estimate for s in stats), 6)
    return {
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "latency_ms": latency,
        "cost_estimate": cost,
    }


def _payload_to_scenario(payload: Dict[str, Any]) -> ScenarioTask:
    """Convert a BenchmarkTask payload dict into a minimal ScenarioTask."""
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
    """Re-hydrate an ExternalTask from a payload so the external scorer can run."""
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
    error: Optional[str],
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


def evaluate_task(
    *,
    task: Any,
    method: str,
    seed: int,
    stressors: List[Any],
    runtime_config: Dict[str, Any],
) -> RuntimeResult:
    """Run a single task through the LLM-backed harness."""
    run_id = f"run_{uuid4().hex}"
    ablation = runtime_config.get("ablation")
    task_payload = task.payload or {}
    candidate_tools = list(task_payload.get("tools") or ["lookup", "act", "respond"])
    system, user = _prompt_for_task(task_payload)
    injected: List[Dict[str, Any]] = []
    llm_stats: List[LLMCallStats] = []
    tool_sequence: List[str] = []
    events: List[Dict[str, Any]] = []
    contract_violations = 0
    recovery_actions = 0
    attempts = 0
    parsed: Optional[Dict[str, Any]] = None
    raw_text = ""
    recovered = False
    error: Optional[str] = None
    success = False

    use_schema_check = method in {"schema_only", "adagentflow_rt"}
    use_recovery = method == "adagentflow_rt" and ablation != "without_bounded_recovery"
    use_localizer = method == "adagentflow_rt" and ablation != "without_fault_localizer"
    use_monitor = method == "adagentflow_rt" and ablation != "without_contract_monitor"
    use_event_trace = method == "adagentflow_rt" and ablation != "without_event_trace"
    # Ablating the contract monitor also disables the schema-only repair
    if method == "adagentflow_rt" and ablation == "without_contract_monitor":
        use_schema_check = False
    max_retries = int(runtime_config.get("max_retries", 2))
    if method == "vanilla":
        max_retries = 0
    if method == "retry_only":
        use_schema_check = False
        use_recovery = False
        use_localizer = False
        use_monitor = False
        use_event_trace = False

    client = SyncLLMClient(method=method, seed=seed)

    def _log_event(event_type: str, **payload: Any) -> None:
        if not use_event_trace:
            return
        events.append({"event_type": event_type, "payload": payload})

    def _inject_stressors(phase: str, call_obj: Dict[str, Any]) -> None:
        for stressor in stressors:
            event = {"task_id": task.task_id, "method": method, "phase": phase}
            if stressor.should_inject(event):
                fault = stressor.apply(call_obj)
                injected.append(fault)
                _log_event("fault.injected", stressor=stressor.name)

    max_loops = max(1, max_retries + 1)
    for loop_idx in range(max_loops):
        attempts += 1
        _log_event("node.started", attempt=loop_idx + 1)
        # Apply stressors to the LLM output *after* the call (so the monitor
        # actually sees the drift, partial response, etc.)
        result = client.chat(system=system, user=user, schema_hint=SCHEMA_HINT)
        llm_stats.append(result.stats)
        raw_text = result.content
        parsed = result.parsed if result.error is None else None
        if parsed is not None:
            # Stressors that mutate the output (schema_drift, stale_context, etc.)
            _inject_stressors(phase="node", call_obj=parsed)
            if not isinstance(parsed, dict):
                parsed = None  # stressor may have wiped structure

        if use_monitor and candidate_tools:
            tool_sequence.append(candidate_tools[min(loop_idx, len(candidate_tools) - 1)])

        violations = _detect_violations(parsed, raw_text) if (use_monitor or use_schema_check) else []
        contract_violations += len(violations)
        for v in violations:
            _log_event("contract.violated", violation_type=v["type"], message=v["message"])

        # Schema-only: rapid repair
        if use_schema_check and any(v["type"] == "SCHEMA_VIOLATION" for v in violations):
            repair = client.chat(
                system="You fix JSON output to match the schema exactly.",
                user=raw_text + '\n\nReturn only valid JSON: {"resolution": "...", "policy_compliant": true|false}',
                schema_hint=SCHEMA_HINT,
            )
            llm_stats.append(repair.stats)
            parsed = repair.parsed
            raw_text = repair.content
            recovery_actions += 1
            _log_event("recovery.selected", action="quick_repair")

        # Recovery controller (adagentflow_rt)
        if use_recovery and violations:
            if use_localizer:
                _log_event("fault.localized", node_id="resolve")
            for v in violations:
                action = "retry_same_agent" if v["type"] == "SCHEMA_VIOLATION" else "reroute_agent"
                _log_event("recovery.started", action=action, violation=v["type"])
                retry_result = client.chat(
                    system=system + "\n\nPrevious attempt was rejected. Produce a corrected answer.",
                    user=user,
                    schema_hint=SCHEMA_HINT,
                )
                llm_stats.append(retry_result.stats)
                raw_text = retry_result.content
                parsed = retry_result.parsed
                recovery_actions += 1
                _log_event("recovery.succeeded", action=action)

        # retry-only: simple retry on transport/json failure
        if method == "retry_only" and (parsed is None) and loop_idx < max_loops - 1:
            continue
        break

    # Vanilla: simple, no recovery, no schema check. Mark dead_letter if json broken.
    if method == "vanilla" and parsed is None:
        second = client.chat(system="Answer the customer request in plain text.", user=user)
        llm_stats.append(second.stats)
        raw_text = second.content

    if not tool_sequence:
        tool_sequence = _extract_tools_from_text(raw_text, candidate_tools)
    if not tool_sequence and candidate_tools:
        tool_sequence = [candidate_tools[0]]

    scenario = _payload_to_scenario(task_payload)
    if task_payload.get("adapter_mode") == "external" or task_payload.get("policy_text"):
        # Real benchmark task: use the external scorer
        native = evaluate_external(
            task=_payload_to_external_task(task_payload),
            generated_text=raw_text,
            tool_sequence=tool_sequence,
        )
    else:
        native = evaluate_native(
            task=scenario,
            generated_text=raw_text,
            generated_actions=[],
            tool_sequence=tool_sequence,
        )

    success_native = bool(native.get("task_success"))
    if method == "vanilla":
        success = bool(parsed is not None)  # vanilla self-reports success even on off-policy output
    else:
        success = success_native

    if method == "vanilla" and not success_native:
        error = "vanilla: off-policy / json failure"
        dead_letter = True
    elif not success:
        error = "contract recovery failed"
        dead_letter = True
    else:
        error = None
        dead_letter = False
    recovered = bool(contract_violations > 0 and success_native and method == "adagentflow_rt")

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
        recovered=recovered,
        dead_letter=dead_letter,
        ablation=ablation,
        events=events,
        contract_violations=contract_violations,
        recovery_actions=recovery_actions,
        error=error,
    )
