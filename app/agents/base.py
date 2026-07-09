"""Agent 基类 - 统一入口，封装：LLM 调用 + JSON 校验 + 自动修复 + 指标记录"""
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from app.core.logging import get_logger
from app.core.failure_codes import FailureReason
from app.services.llm_client import get_llm_client, LLMClient, LLMJsonError, LLMError
from app.services.json_validator import (
    validate_json_output,
    build_repair_prompt,
    JsonValidationError,
    quick_json_repair,
)
from app.schemas.agent_schemas import pydantic_to_json_schema
from app.db.database import session_scope
from app.models.metric import AgentMetric

logger = get_logger()


@dataclass
class AgentResult:
    """统一 Agent 结果"""

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


class BaseAgent:
    step_id: str = "base"
    prompt_version: str = "v1.0"

    def __init__(self):
        self.llm: LLMClient = get_llm_client()

    # 子类必须覆盖
    def build_system_prompt(self) -> str:
        raise NotImplementedError

    def build_user_prompt(self, ctx: Dict[str, Any]) -> str:
        raise NotImplementedError

    # ============================================================
    # 统一执行入口
    # ============================================================
    async def run(self, ctx: Dict[str, Any]) -> AgentResult:
        """执行 Agent

        ctx: 上下文，包含 product, history_outputs, failure_feedback 等
        """
        start = time.time()
        result = AgentResult(success=False, model=self.llm.model, prompt_version=self.prompt_version)

        system_prompt = self.build_system_prompt()
        user_prompt = self.build_user_prompt(ctx)

        try:
            parsed, llm_resp = await self.llm.generate_json(
                user_prompt,
                system_prompt=system_prompt,
                prompt_version=self.prompt_version,
                step_id=self.step_id,
            )
            result.raw_output = llm_resp.content
            result.input_tokens += llm_resp.input_tokens
            result.output_tokens += llm_resp.output_tokens

            # 校验 Schema
            parsed, _ = validate_json_output(self.step_id, llm_resp.content)
            result.output = parsed
            result.success = True
            result.latency_ms = int((time.time() - start) * 1000)
            self._update_metric(success=True, json_failed=False)
            return result

        except (LLMJsonError, JsonValidationError) as e:
            # 自动修复一轮
            logger.warning(f"[{self.step_id}] 校验失败，尝试自动修复: {e}")
            result.failure_reason = e.error_type if hasattr(e, "error_type") else FailureReason.SCHEMA_VALIDATION_ERROR.value
            result.error_message = str(e)
            raw_content = (
                e.raw_content if isinstance(e, JsonValidationError) else (
                    result.raw_output or ""
                )
            )
            error_details = e.error_details if isinstance(e, JsonValidationError) else [str(e)]

            # 1. 先试本地 quick repair
            local_repaired = quick_json_repair(raw_content)
            if local_repaired is not None:
                try:
                    parsed, _ = validate_json_output(self.step_id, json_dumps(local_repaired))
                    result.output = parsed
                    result.raw_output = json_dumps(local_repaired)
                    result.success = True
                    result.latency_ms = int((time.time() - start) * 1000)
                    self._update_metric(success=True, json_failed=True)
                    return result
                except Exception:
                    pass

            # 2. 调用 LLM 修复
            repair_prompt = build_repair_prompt(
                self.step_id,
                raw_content or "",
                error_details,
                original_system=system_prompt,
            )
            try:
                repaired, repaired_resp = await self.llm.generate_json(
                    repair_prompt,
                    system_prompt=system_prompt,
                    prompt_version=self.prompt_version + ".repair",
                    step_id=self.step_id,
                )
                result.repairs_attempted = 1
                result.input_tokens += repaired_resp.input_tokens
                result.output_tokens += repaired_resp.output_tokens
                result.raw_output = repaired_resp.content
                parsed, _ = validate_json_output(self.step_id, repaired_resp.content)
                result.output = parsed
                result.success = True
                result.latency_ms = int((time.time() - start) * 1000)
                self._update_metric(success=True, json_failed=True)
                return result
            except Exception as ee:
                logger.error(f"[{self.step_id}] 自动修复后仍然失败: {ee}")
                result.needs_repair_agent = True
                result.repair_payload = {
                    "original_output": raw_content,
                    "error_details": error_details,
                    "failure_reason": result.failure_reason,
                }

        except LLMError as e:
            logger.error(f"[{self.step_id}] LLM 错误: {e}")
            result.failure_reason = e.error_type if hasattr(e, "error_type") else FailureReason.MODEL_TIMEOUT.value
            result.error_message = str(e)
            result.needs_retry = e.retryable

        except Exception as e:
            logger.error(f"[{self.step_id}] 未预期异常: {e}\n{traceback.format_exc()}")
            result.failure_reason = FailureReason.UNKNOWN_ERROR.value
            result.error_message = str(e)
            result.needs_retry = True

        result.latency_ms = int((time.time() - start) * 1000)
        self._update_metric(success=False, json_failed=result.failure_reason in (
            FailureReason.JSON_PARSE_ERROR.value, FailureReason.SCHEMA_VALIDATION_ERROR.value
        ))
        return result

    def _update_metric(self, success: bool, json_failed: bool):
        """更新节点级指标"""
        try:
            with session_scope() as db:
                m = db.query(AgentMetric).filter(AgentMetric.step_name == self.step_id).first()
                if m is None:
                    m = AgentMetric(step_name=self.step_id)
                    db.add(m)
                    db.flush()
                m.total_executions = (m.total_executions or 0) + 1
                if success:
                    m.success_executions = (m.success_executions or 0) + 1
                else:
                    m.failed_executions = (m.failed_executions or 0) + 1
                if json_failed:
                    m.json_failures = (m.json_failures or 0) + 1
                    if not success:
                        m.schema_failures = (m.schema_failures or 0) + 1
        except Exception as e:
            logger.warning(f"更新指标失败: {e}")


def json_dumps(o: Any) -> str:
    import json

    return json.dumps(o, ensure_ascii=False)
