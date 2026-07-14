"""Prompt-agent abstraction; execution governance lives in AgentExecutor."""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.agents.contracts import AgentResult, AgentSpec
from app.agents.executor import AgentExecutor
from app.services.llm_client import LLMClient, get_llm_client
from app.services.tracing import Tracer


class BaseAgent:
    """Base for prompt construction and optional output post-processing.

    ``run`` remains as a compatibility facade for callers while delegating all
    runtime concerns to ``AgentExecutor``.
    """

    step_id: str = "base"
    prompt_version: str = "v1.0"

    def __init__(
        self,
        *,
        spec: Optional[AgentSpec] = None,
        llm: Optional[LLMClient] = None,
        executor: Optional[AgentExecutor] = None,
    ):
        self.spec = spec or AgentSpec(
            step_id=self.step_id,
            agent_class=type(self),
            output_schema=None,
        )
        self.llm = llm or get_llm_client()
        self.executor = executor or AgentExecutor()

    def build_system_prompt(self) -> str:
        raise NotImplementedError

    def build_user_prompt(self, ctx: Dict[str, Any]) -> str:
        raise NotImplementedError

    def validation_schema_name(self, ctx: Dict[str, Any]) -> str:
        return self.step_id

    def postprocess_output(
        self, output: Dict[str, Any], ctx: Dict[str, Any]
    ) -> Dict[str, Any]:
        return output

    async def run(
        self, ctx: Dict[str, Any], tracer: Optional[Tracer] = None
    ) -> AgentResult:
        return await self.executor.execute(self, ctx, tracer=tracer)


__all__ = ["AgentResult", "AgentSpec", "BaseAgent"]
