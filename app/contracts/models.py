"""Core contract dataclasses for the contractual runtime."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ResourceBudget:
    max_latency_ms: Optional[int] = None
    max_llm_calls: Optional[int] = None
    max_tool_calls: Optional[int] = None
    max_tokens: Optional[int] = None
    max_retries: int = 0


@dataclass
class RecoveryPolicy:
    actions: List[str] = field(default_factory=list)
    max_attempts: int = 0
    rollback_target: Optional[str] = None
    escalate_on: List[str] = field(default_factory=list)


@dataclass
class Contract:
    name: str
    capability: str
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    preconditions: List[str] = field(default_factory=list)
    postconditions: List[str] = field(default_factory=list)
    semantic_checks: List[str] = field(default_factory=list)
    resource_budget: ResourceBudget = field(default_factory=ResourceBudget)
    recovery_policy: Dict[str, List[str]] = field(default_factory=dict)
    escalation_policy: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Artifact:
    artifact_id: str
    producer_node: str
    content: Dict[str, Any]
    contract_name: str
    validation_status: str
    provenance: Dict[str, Any] = field(default_factory=dict)
    downstream_consumers: List[str] = field(default_factory=list)


@dataclass
class ContractViolation:
    task_id: str
    node_id: str
    contract_name: str
    violation_type: str
    message: str
    severity: str
    recoverable: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
