"""Policy constants for violation handling and recovery."""
from __future__ import annotations

from typing import Dict, List

DEFAULT_RECOVERY_POLICY: Dict[str, List[str]] = {
    "SCHEMA_VIOLATION": ["quick_repair", "retry_same_agent", "dead_letter"],
    "PRECONDITION_FAILED": ["rollback_to_checkpoint", "retry_same_agent", "dead_letter"],
    "POSTCONDITION_FAILED": ["retry_same_agent", "reroute_agent", "dead_letter"],
    "SEMANTIC_DRIFT": ["reroute_agent", "rollback_to_checkpoint", "human_escalate"],
    "BUDGET_EXCEEDED": ["degrade_output", "dead_letter"],
    "TOOL_FAILURE": ["retry_same_agent", "reroute_agent", "dead_letter"],
    "TIMEOUT": ["retry_same_agent", "degrade_output", "dead_letter"],
    "DUPLICATE_EXECUTION": ["invalidate_downstream"],
    "STALE_CONTEXT": ["rollback_to_checkpoint", "retry_same_agent", "dead_letter"],
    "UNKNOWN": ["retry_same_agent", "dead_letter"],
}


RECOVERABLE_ACTIONS = {
    "quick_repair",
    "llm_repair",
    "retry_same_agent",
    "reroute_agent",
    "rollback_to_checkpoint",
    "invalidate_downstream",
    "degrade_output",
}


TERMINAL_ACTIONS = {"human_escalate", "dead_letter"}
