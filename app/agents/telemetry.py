"""Best-effort Agent telemetry, isolated from prompt and execution logic."""
from __future__ import annotations

from typing import Optional

from app.agents.contracts import AgentResult
from app.core.logging import get_logger
from app.db.database import session_scope
from app.models.metric import AgentMetric
from app.services.tracing import Tracer

logger = get_logger()


class AgentTelemetry:
    """Records traces and aggregate metrics without breaking the main path."""

    def start(self, tracer: Optional[Tracer], task_id: str, step_id: str) -> None:
        if tracer is None or not task_id:
            return
        try:
            tracer.record_step_start(task_id=task_id, step_id=step_id)
        except Exception as exc:
            logger.warning(f"trace.start write failed: {exc}")

    def success(
        self, tracer: Optional[Tracer], task_id: str, step_id: str, result: AgentResult
    ) -> None:
        self._update_metric(step_id, result, json_failed=result.repairs_attempted > 0)
        if tracer is None or not task_id:
            return
        try:
            tracer.record_step_success(
                task_id=task_id,
                step_id=step_id,
                latency_ms=result.latency_ms,
                model_name=result.model,
                prompt_version=result.prompt_version,
                token_cost=result.input_tokens + result.output_tokens,
                extra_metadata={"repairs_attempted": result.repairs_attempted},
            )
        except Exception as exc:
            logger.warning(f"trace.success write failed: {exc}")

    def failure(
        self, tracer: Optional[Tracer], task_id: str, step_id: str, result: AgentResult
    ) -> None:
        json_failed = result.failure_reason in {"JSON_PARSE_ERROR", "SCHEMA_VALIDATION_ERROR"}
        self._update_metric(step_id, result, json_failed=json_failed)
        if tracer is None or not task_id:
            return
        try:
            tracer.record_step_fail(
                task_id=task_id,
                step_id=step_id,
                latency_ms=result.latency_ms,
                error_message=result.error_message,
                failure_reason=result.failure_reason,
                extra_metadata={
                    "repairs_attempted": result.repairs_attempted,
                    "needs_retry": result.needs_retry,
                    "needs_repair_agent": result.needs_repair_agent,
                },
            )
        except Exception as exc:
            logger.warning(f"trace.fail write failed: {exc}")

    def _update_metric(self, step_id: str, result: AgentResult, json_failed: bool) -> None:
        try:
            with session_scope() as db:
                metric = db.query(AgentMetric).filter(AgentMetric.step_name == step_id).first()
                if metric is None:
                    metric = AgentMetric(step_name=step_id)
                    db.add(metric)
                    db.flush()
                metric.total_executions = (metric.total_executions or 0) + 1
                if result.success:
                    metric.success_executions = (metric.success_executions or 0) + 1
                else:
                    metric.failed_executions = (metric.failed_executions or 0) + 1
                if json_failed:
                    metric.json_failures = (metric.json_failures or 0) + 1
                    if not result.success:
                        metric.schema_failures = (metric.schema_failures or 0) + 1
                metric.total_token_cost = (
                    (metric.total_token_cost or 0)
                    + result.input_tokens
                    + result.output_tokens
                )
                metric.total_latency_ms = (metric.total_latency_ms or 0) + result.latency_ms
        except Exception as exc:
            logger.warning(f"agent metric update failed: {exc}")
