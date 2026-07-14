"""Governed execution pipeline shared by all prompt agents."""
from __future__ import annotations

import asyncio
import json
import time
import traceback
from typing import Any, Dict, Optional, TYPE_CHECKING

from app.agents.contracts import AgentResult
from app.agents.telemetry import AgentTelemetry
from app.core.failure_codes import FailureReason
from app.core.logging import get_logger
from app.services.json_validator import (
    JsonValidationError,
    build_repair_prompt,
    quick_json_repair,
    validate_json_output,
)
from app.services.llm_client import LLMError, LLMJsonError
from app.services.tracing import Tracer

if TYPE_CHECKING:
    from app.agents.base import BaseAgent

logger = get_logger()


class AgentExecutor:
    """Owns timeout, validation, repair, error mapping and telemetry."""

    def __init__(self, telemetry: Optional[AgentTelemetry] = None):
        self.telemetry = telemetry or AgentTelemetry()

    async def execute(
        self, agent: "BaseAgent", ctx: Dict[str, Any], tracer: Optional[Tracer] = None
    ) -> AgentResult:
        started_at = time.monotonic()
        result = AgentResult(
            success=False,
            model=agent.llm.model,
            prompt_version=agent.prompt_version,
        )
        task_id = ctx.get("task_id") or ""
        if not task_id and isinstance(ctx.get("payload"), dict):
            task_id = ctx["payload"].get("task_id", "")
        self.telemetry.start(tracer, task_id, agent.step_id)

        try:
            async with asyncio.timeout(agent.spec.timeout_seconds):
                await self._generate(agent, ctx, result)
        except TimeoutError:
            result.failure_reason = FailureReason.MODEL_TIMEOUT.value
            result.error_message = f"agent execution exceeded {agent.spec.timeout_seconds:g}s"
            result.needs_retry = True
        except LLMError as exc:
            logger.error(f"[{agent.step_id}] LLM error: {exc}")
            result.failure_reason = getattr(exc, "error_type", FailureReason.MODEL_TIMEOUT.value)
            result.error_message = str(exc)
            result.needs_retry = exc.retryable
        except Exception as exc:
            logger.error(f"[{agent.step_id}] unexpected error: {exc}\n{traceback.format_exc()}")
            result.failure_reason = FailureReason.UNKNOWN_ERROR.value
            result.error_message = str(exc)
            result.needs_retry = True

        result.latency_ms = int((time.monotonic() - started_at) * 1000)
        if result.success:
            self.telemetry.success(tracer, task_id, agent.step_id, result)
        else:
            self.telemetry.failure(tracer, task_id, agent.step_id, result)
        return result

    async def _generate(
        self, agent: "BaseAgent", ctx: Dict[str, Any], result: AgentResult
    ) -> None:
        system_prompt = agent.build_system_prompt()
        user_prompt = agent.build_user_prompt(ctx)
        schema_name = agent.validation_schema_name(ctx)
        try:
            _, response = await agent.llm.generate_json(
                user_prompt,
                system_prompt=system_prompt,
                prompt_version=agent.prompt_version,
                step_id=schema_name,
            )
            self._merge_response(result, response)
            parsed, _ = validate_json_output(schema_name, response.content)
            result.output = agent.postprocess_output(parsed, ctx)
            result.success = True
        except (LLMJsonError, JsonValidationError) as exc:
            await self._repair(agent, ctx, result, schema_name, system_prompt, exc)

    async def _repair(self, agent, ctx, result, schema_name, system_prompt, exc) -> None:
        logger.warning(f"[{agent.step_id}] validation failed, attempting repair: {exc}")
        result.failure_reason = getattr(
            exc, "error_type", FailureReason.SCHEMA_VALIDATION_ERROR.value
        )
        result.error_message = str(exc)
        raw_content = (
            exc.raw_content
            if isinstance(exc, JsonValidationError)
            else (result.raw_output or "")
        )
        error_details = exc.error_details if isinstance(exc, JsonValidationError) else [str(exc)]

        local_repaired = quick_json_repair(raw_content)
        if local_repaired is not None:
            try:
                repaired_json = json.dumps(local_repaired, ensure_ascii=False)
                parsed, _ = validate_json_output(schema_name, repaired_json)
                result.output = agent.postprocess_output(parsed, ctx)
                result.raw_output = repaired_json
                result.success = True
                result.repairs_attempted = 1
                return
            except Exception:
                pass

        if not agent.spec.retry_policy.enable_schema_repair:
            result.needs_repair_agent = True
            return

        repair_prompt = build_repair_prompt(
            schema_name, raw_content, error_details, original_system=system_prompt
        )
        try:
            _, response = await agent.llm.generate_json(
                repair_prompt,
                system_prompt=system_prompt,
                prompt_version=agent.prompt_version + ".repair",
                step_id=schema_name,
            )
            result.repairs_attempted = 1
            self._merge_response(result, response)
            parsed, _ = validate_json_output(schema_name, response.content)
            result.output = agent.postprocess_output(parsed, ctx)
            result.success = True
        except Exception as repair_exc:
            logger.error(f"[{agent.step_id}] repair failed: {repair_exc}")
            result.needs_repair_agent = True
            result.repair_payload = {
                "original_output": raw_content,
                "error_details": error_details,
                "failure_reason": result.failure_reason,
            }

    @staticmethod
    def _merge_response(result: AgentResult, response: Any) -> None:
        result.raw_output = response.content
        result.input_tokens += response.input_tokens
        result.output_tokens += response.output_tokens
        if response.model:
            result.model = response.model
        if response.prompt_version:
            result.prompt_version = response.prompt_version
