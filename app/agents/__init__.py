"""Public Agent API backed by the declarative runtime registry."""
from types import MappingProxyType

from app.agents.contracts import AgentResult, AgentSpec, ModelPolicy, RetryPolicy
from app.agents.evaluation_agent import QualityEvaluationAgent
from app.agents.material_agent import MaterialSuggestionAgent
from app.agents.product_analysis_agent import ProductAnalysisAgent
from app.agents.registry import AGENT_REGISTRY, AgentRegistry
from app.agents.repair_agent import RepairAgent
from app.agents.script_agent import ScriptGenerationAgent
from app.agents.storyboard_agent import StoryboardPlanningAgent

# Backward-compatible read-only view. New code should consume AGENT_REGISTRY/specs.
ALL_AGENTS = MappingProxyType(
    {step_id: spec.agent_class for step_id, spec in AGENT_REGISTRY.specs.items()}
)


def get_agent(step_id: str):
    return AGENT_REGISTRY.create(step_id)


def get_agent_spec(step_id: str) -> AgentSpec:
    return AGENT_REGISTRY.spec(step_id)


__all__ = [
    "AGENT_REGISTRY",
    "ALL_AGENTS",
    "AgentRegistry",
    "AgentResult",
    "AgentSpec",
    "ModelPolicy",
    "RetryPolicy",
    "get_agent",
    "get_agent_spec",
    "ProductAnalysisAgent",
    "ScriptGenerationAgent",
    "StoryboardPlanningAgent",
    "MaterialSuggestionAgent",
    "QualityEvaluationAgent",
    "RepairAgent",
]
