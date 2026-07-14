"""Declarative Agent registry: the runtime control-plane source of truth."""
from __future__ import annotations

from types import MappingProxyType
from typing import Dict, Iterable, Mapping

from app.agents.contracts import AgentSpec, RetryPolicy
from app.agents.evaluation_agent import QualityEvaluationAgent
from app.agents.material_agent import MaterialSuggestionAgent
from app.agents.product_analysis_agent import ProductAnalysisAgent
from app.agents.repair_agent import RepairAgent
from app.agents.script_agent import ScriptGenerationAgent
from app.agents.storyboard_agent import StoryboardPlanningAgent
from app.schemas.agent_schemas import (
    EvaluationSchema,
    MaterialSuggestionSchema,
    ProductAnalysisSchema,
    ScriptSchema,
    StoryboardSchema,
)


class AgentRegistry:
    def __init__(self, specs: Iterable[AgentSpec] = ()):
        self._specs: Dict[str, AgentSpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: AgentSpec) -> None:
        if spec.step_id in self._specs:
            raise ValueError(f"duplicate agent step_id: {spec.step_id}")
        declared_step = getattr(spec.agent_class, "step_id", None)
        if declared_step != spec.step_id:
            raise ValueError(
                f"agent class step_id mismatch: registry={spec.step_id}, class={declared_step}"
            )
        self._specs[spec.step_id] = spec

    def spec(self, step_id: str) -> AgentSpec:
        try:
            return self._specs[step_id]
        except KeyError as exc:
            raise KeyError(f"unknown agent step_id: {step_id}") from exc

    def create(self, step_id: str):
        spec = self.spec(step_id)
        return spec.agent_class(spec=spec)

    @property
    def specs(self) -> Mapping[str, AgentSpec]:
        return MappingProxyType(self._specs)


AGENT_REGISTRY = AgentRegistry(
    [
        AgentSpec("product_analysis", ProductAnalysisAgent, ProductAnalysisSchema),
        AgentSpec("script_generation", ScriptGenerationAgent, ScriptSchema),
        AgentSpec("storyboard_planning", StoryboardPlanningAgent, StoryboardSchema),
        AgentSpec("material_suggestion", MaterialSuggestionAgent, MaterialSuggestionSchema),
        AgentSpec("quality_evaluation", QualityEvaluationAgent, EvaluationSchema),
        AgentSpec(
            "repair",
            RepairAgent,
            None,
            timeout_seconds=90,
            max_concurrency=4,
            retry_policy=RetryPolicy(max_attempts=2, backoff_seconds=(5, 30)),
            degradation_strategy="dead_letter_for_human_recovery",
        ),
    ]
)
