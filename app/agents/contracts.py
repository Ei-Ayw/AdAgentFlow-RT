"""Agent runtime contracts and governance metadata."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple, Type

from pydantic import BaseModel


@dataclass(frozen=True)
class RetryPolicy:
    """Retry intent exposed to orchestration and operations tooling."""

    max_attempts: int = 3
    backoff_seconds: Tuple[int, ...] = (5, 30, 120)
    enable_schema_repair: bool = True


@dataclass(frozen=True)
class ModelPolicy:
    """Model routing policy. Empty model names defer to the LLM client config."""

    primary: Optional[str] = None
    fallbacks: Tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentSpec:
    """Declarative definition of one workflow agent.

    The registry is the control-plane source of truth; concrete agents only own
    prompt construction and optional output post-processing.
    """

    step_id: str
    agent_class: Type[Any]
    output_schema: Optional[Type[BaseModel]]
    timeout_seconds: float = 120.0
    max_concurrency: int = 8
    queue_type: str = "light"
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    model_policy: ModelPolicy = field(default_factory=ModelPolicy)
    idempotency_scope: str = "task_step"
    output_version: str = "v1"
    degradation_strategy: str = "retry_then_dead_letter"
    allow_human_recovery: bool = True

    def __post_init__(self) -> None:
        if not self.step_id:
            raise ValueError("AgentSpec.step_id must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("AgentSpec.timeout_seconds must be positive")
        if self.max_concurrency <= 0:
            raise ValueError("AgentSpec.max_concurrency must be positive")


@dataclass
class AgentResult:
    """Stable result contract consumed by the workflow orchestrator."""

    success: bool
    output: Optional[Dict[str, Any]] = None
    raw_output: Optional[str] = None
    failure_reason: Optional[str] = None
    error_message: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    model: str = ""
    prompt_version: str = "v1.0"
    repairs_attempted: int = 0
    needs_retry: bool = False
    needs_repair_agent: bool = False
    repair_payload: Dict[str, Any] = field(default_factory=dict)
