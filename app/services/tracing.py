"""Trace 服务 - Langfuse + DB 双写
支持 trace_id 全链路追踪
"""
import time
import uuid
from typing import Optional, Dict, Any
from contextlib import contextmanager

from app.core.logging import get_logger
from app.core.config import settings
from app.db.database import session_scope
from app.models.trace import TaskTrace

logger = get_logger()


def generate_trace_id() -> str:
    """全局唯一 trace_id  -  trace_时间戳_随机"""
    return f"trace_{int(time.time())}_{uuid.uuid4().hex[:8]}"


def generate_task_id() -> str:
    return f"task_{int(time.time())}_{uuid.uuid4().hex[:8]}"


class Tracer:
    """轻量 tracer - 把事件写到 task_traces 表，可挂 Langfuse"""

    def __init__(self, trace_id: str):
        self.trace_id = trace_id

    def record(
        self,
        *,
        task_id: Optional[str] = None,
        step_id: Optional[str] = None,
        event_type: str = "step.event",
        event_status: str = "info",
        latency_ms: int = 0,
        model_name: Optional[str] = None,
        prompt_version: Optional[str] = None,
        token_cost: int = 0,
        error_message: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ):
        """写一条 trace - 异常吞掉，不影响主流程"""
        try:
            with session_scope() as db:
                rec = TaskTrace(
                    trace_id=self.trace_id,
                    task_id=task_id,
                    step_id=step_id,
                    event_type=event_type,
                    event_status=event_status,
                    latency_ms=latency_ms,
                    model_name=model_name,
                    prompt_version=prompt_version,
                    token_cost=token_cost,
                    error_message=error_message,
                    extra_metadata=extra_metadata,
                )
                db.add(rec)
        except Exception as e:
            logger.warning(f"写 trace 失败 (非致命): {e}")

    # ================================================================
    # 便捷封装：节点成功 / 失败上报
    # ================================================================
    def record_step_success(
        self,
        *,
        task_id: str,
        step_id: str,
        latency_ms: int = 0,
        model_name: Optional[str] = None,
        prompt_version: Optional[str] = None,
        token_cost: int = 0,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ):
        """封装 step.success 的上报 - 把真实 model/prompt_version/token_cost 全部写进去"""
        self.record(
            task_id=task_id,
            step_id=step_id,
            event_type="step.success",
            event_status="success",
            latency_ms=latency_ms,
            model_name=model_name,
            prompt_version=prompt_version,
            token_cost=token_cost,
            extra_metadata=extra_metadata,
        )

    def record_step_fail(
        self,
        *,
        task_id: str,
        step_id: str,
        latency_ms: int = 0,
        error_message: Optional[str] = None,
        failure_reason: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ):
        """封装 step.fail 的上报"""
        meta = dict(extra_metadata or {})
        if failure_reason is not None:
            meta.setdefault("failure_reason", failure_reason)
        self.record(
            task_id=task_id,
            step_id=step_id,
            event_type="step.fail",
            event_status="failed",
            latency_ms=latency_ms,
            error_message=error_message,
            extra_metadata=meta,
        )

    def record_step_start(
        self,
        *,
        task_id: str,
        step_id: str,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ):
        """封装 step.start 的上报"""
        self.record(
            task_id=task_id,
            step_id=step_id,
            event_type="step.start",
            event_status="running",
            extra_metadata=extra_metadata,
        )


@contextmanager
def trace_step(tracer: Tracer, step_id: str, task_id: str = ""):
    """with 上下文 - 自动写开始/结束 trace"""
    start = time.time()
    tracer.record(
        task_id=task_id,
        step_id=step_id,
        event_type="step.start",
        event_status="started",
        latency_ms=0,
    )
    try:
        yield
        latency = int((time.time() - start) * 1000)
        tracer.record(
            task_id=task_id,
            step_id=step_id,
            event_type="step.end",
            event_status="success",
            latency_ms=latency,
        )
    except Exception as e:
        latency = int((time.time() - start) * 1000)
        tracer.record(
            task_id=task_id,
            step_id=step_id,
            event_type="step.end",
            event_status="failed",
            latency_ms=latency,
            error_message=str(e),
        )
        raise
