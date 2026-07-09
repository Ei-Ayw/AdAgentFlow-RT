"""Contract validation helpers."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

try:
    from jsonschema import Draft202012Validator
except ModuleNotFoundError:  # pragma: no cover - exercised only in minimal envs
    Draft202012Validator = None

from app.contracts.models import Contract, ContractViolation


SCHEMA_VIOLATION = "SCHEMA_VIOLATION"
PRECONDITION_FAILED = "PRECONDITION_FAILED"
POSTCONDITION_FAILED = "POSTCONDITION_FAILED"
SEMANTIC_DRIFT = "SEMANTIC_DRIFT"
BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
DUPLICATE_EXECUTION = "DUPLICATE_EXECUTION"


def validate_schema(
    *,
    task_id: str,
    node_id: str,
    contract: Contract,
    payload: Dict[str, Any],
    direction: str = "output",
) -> List[ContractViolation]:
    schema = contract.output_schema if direction == "output" else contract.input_schema
    if not schema:
        return []
    if Draft202012Validator is None:
        return _validate_schema_minimal(
            task_id=task_id,
            node_id=node_id,
            contract=contract,
            payload=payload,
            schema=schema,
            direction=direction,
        )
    validator = Draft202012Validator(schema)
    violations: List[ContractViolation] = []
    for err in sorted(validator.iter_errors(payload), key=lambda e: list(e.path)):
        path = ".".join(str(part) for part in err.path) or "$"
        violations.append(
            ContractViolation(
                task_id=task_id,
                node_id=node_id,
                contract_name=contract.name,
                violation_type=SCHEMA_VIOLATION,
                message=f"{direction} schema failed at {path}: {err.message}",
                severity="error",
                recoverable=True,
                metadata={"path": path, "validator": err.validator},
            )
        )
    return violations


def _validate_schema_minimal(
    *,
    task_id: str,
    node_id: str,
    contract: Contract,
    payload: Dict[str, Any],
    schema: Dict[str, Any],
    direction: str,
) -> List[ContractViolation]:
    violations: List[ContractViolation] = []
    for key in schema.get("required", []):
        if key not in payload:
            violations.append(
                ContractViolation(
                    task_id=task_id,
                    node_id=node_id,
                    contract_name=contract.name,
                    violation_type=SCHEMA_VIOLATION,
                    message=f"{direction} schema failed at {key}: required property missing",
                    severity="error",
                    recoverable=True,
                    metadata={"path": key, "validator": "required"},
                )
            )
    type_map = {"string": str, "boolean": bool, "number": (int, float), "integer": int, "object": dict}
    for key, spec in (schema.get("properties") or {}).items():
        expected = type_map.get(spec.get("type")) if isinstance(spec, dict) else None
        if expected and key in payload and not isinstance(payload[key], expected):
            violations.append(
                ContractViolation(
                    task_id=task_id,
                    node_id=node_id,
                    contract_name=contract.name,
                    violation_type=SCHEMA_VIOLATION,
                    message=f"{direction} schema failed at {key}: expected {spec.get('type')}",
                    severity="error",
                    recoverable=True,
                    metadata={"path": key, "validator": "type"},
                )
            )
    return violations


def check_required_artifacts(
    *,
    task_id: str,
    node_id: str,
    contract: Contract,
    required_artifacts: Iterable[str],
    available_artifacts: Iterable[str],
) -> List[ContractViolation]:
    available = set(available_artifacts)
    missing = [artifact_id for artifact_id in required_artifacts if artifact_id not in available]
    if not missing:
        return []
    return [
        ContractViolation(
            task_id=task_id,
            node_id=node_id,
            contract_name=contract.name,
            violation_type=PRECONDITION_FAILED,
            message=f"missing required artifacts: {', '.join(missing)}",
            severity="error",
            recoverable=True,
            metadata={"missing_artifacts": missing},
        )
    ]


def check_budget(
    *,
    task_id: str,
    node_id: str,
    contract: Contract,
    observed: Dict[str, int],
) -> List[ContractViolation]:
    budget = contract.resource_budget
    checks = {
        "latency_ms": budget.max_latency_ms,
        "llm_calls": budget.max_llm_calls,
        "tool_calls": budget.max_tool_calls,
        "tokens": budget.max_tokens,
        "retries": budget.max_retries,
    }
    violations: List[ContractViolation] = []
    for key, limit in checks.items():
        if limit is None:
            continue
        value = int(observed.get(key, 0) or 0)
        if value > limit:
            violations.append(
                ContractViolation(
                    task_id=task_id,
                    node_id=node_id,
                    contract_name=contract.name,
                    violation_type=BUDGET_EXCEEDED,
                    message=f"{key} budget exceeded: observed={value}, limit={limit}",
                    severity="warning",
                    recoverable=True,
                    metadata={"metric": key, "observed": value, "limit": limit},
                )
            )
    return violations
