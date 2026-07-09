"""工作流编排器 - 控制 step 链式执行 + 任务状态机推进"""
import time
import asyncio
import json
import datetime
from typing import Dict, Any, Optional

from app.core.config import settings
from app.core.state_machine import (
    TaskStatus,
    StepStatus,
    WORKFLOW_STEPS,
    STEP_NAME_DISPLAY,
    next_step_or_done,
    assert_transition_task,
    assert_transition_step,
)
from app.core.logging import get_logger
from app.core.failure_codes import FailureReason
from app.db.database import session_scope
from app.models.task import Task
from app.models.step import TaskStep
from app.models.evaluation import EvaluationResult
from app.agents import get_agent
from app.agents.base import AgentResult
from app.services.queue import get_queue_client
from app.services.tracing import generate_task_id, generate_trace_id, Tracer
from app.services.retry import (
    mark_task_retrying,
    send_to_dead_letter,
    compute_retry_delay,
    should_retry,
)
from app.services.idempotency import acquire_idempotent

logger = get_logger()


class WorkflowOrchestrator:
    """Workflow + 任务状态机 + 重试协调

    step chain:
      product_analysis → script_generation → storyboard_planning
      → material_suggestion → quality_evaluation
      → (optional) repair ...
    """

    def __init__(self):
        self.queue = get_queue_client()

    # ============================================================
    # 入口 - 创建新任务
    # ============================================================
    async def create_task(self, product: Dict[str, Any]) -> str:
        """接收新商品信息，写库，推入队列

        Returns:
            task_id
        """
        from app.services.tracing import generate_task_id

        task_id = generate_task_id()
        trace_id = generate_trace_id()

        with session_scope() as db:
            t = Task(
                task_id=task_id,
                trace_id=trace_id,
                status=TaskStatus.CREATED.value,
                product_name=product.get("product_name", ""),
                platform=product.get("platform", ""),
                style=product.get("style", ""),
                duration=product.get("duration", 15),
                target_user=product.get("target_user", ""),
                selling_points=product.get("selling_points", []),
                input_payload=product,
                max_retry=settings.max_retry_count,
                retry_count=0,
            )
            db.add(t)
            # 预先插入 step 占位
            for step_id in WORKFLOW_STEPS:
                step = TaskStep(
                    task_id=task_id,
                    step_id=step_id,
                    step_name=STEP_NAME_DISPLAY.get(step_id, step_id),
                    status=StepStatus.PENDING.value,
                )
                db.add(step)

        await self.queue.connect()
        await self.queue.publish_step(
            task_id,
            WORKFLOW_STEPS[0],
            {
                "task_id": task_id,
                "trace_id": trace_id,
                "product": product,
                "history": {},
                "attempt": 1,
            },
        )
        logger.info(f"任务已创建并派发: task_id={task_id}, trace_id={trace_id}")
        return task_id

    # ============================================================
    # 入口 - 接管死信任务（人工提交）
    # ============================================================
    async def resume_dead_letter(self, task_id: str) -> bool:
        """把死信任务拉回队列重跑（重置 retry_count）"""
        with session_scope() as db:
            task = db.query(Task).filter(Task.task_id == task_id).first()
            if not task:
                return False
            if task.status != TaskStatus.DEAD_LETTER.value:
                return False
            assert_transition_task(task.status, TaskStatus.QUEUED.value)
            task.status = TaskStatus.QUEUED.value
            task.retry_count = 0
            steps = db.query(TaskStep).filter(TaskStep.task_id == task_id).all()
            for s in steps:
                s.status = StepStatus.PENDING.value
                s.retry_count = 0

        # 重新派第一个 step
        with session_scope() as db:
            history = self._collect_history(db, task_id)
        await self.queue.publish_step(
            task_id,
            WORKFLOW_STEPS[0],
            {
                "task_id": task_id,
                "trace_id": self._trace_id_of(task_id),
                "product": self._product_of(task_id),
                "history": history,
                "attempt": 1,
                "resumed_from_dead_letter": True,
            },
        )
        return True

    # ============================================================
    # Worker 调用的入口 - 执行单个 step
    # ============================================================
    async def execute_step(self, task_id: str, step_id: str, payload: Dict[str, Any]):
        """执行 step - 由 worker 循环回调

        流程：
        1. 幂等检查
        2. 推进任务状态到 running
        3. 推进 step 状态到 running
        4. 调用 Agent.run()
        5. 处理结果（成功推进 / 失败重试 / 死信）
        """
        trace_id = payload.get("trace_id", generate_trace_id())
        tracer = Tracer(trace_id)
        attempt = payload.get("attempt", 1)
        product = payload.get("product", {})
        history = payload.get("history", {})
        failure_feedback = payload.get("failure_feedback", "")

        # 1. 幂等拦截
        if not await acquire_idempotent(task_id, step_id):
            logger.warning(f"[{step_id}] {task_id} 已被持有，跳过重复消费")
            return

        # 推进任务状态到 running（按状态机校验）
        self._transition_task(task_id, TaskStatus.RUNNING.value)
        # 推进 step 到 running
        self._transition_step(task_id, step_id, StepStatus.RUNNING.value)
        # 注：start 事件由 agent.run 内部统一写，避免重复

        # 取 agent
        agent = get_agent(step_id)

        # 上下文传给 agent
        ctx = {
            "task_id": task_id,
            "trace_id": trace_id,
            "product": product,
            "history": history,
            "attempt": attempt,
            "failure_feedback": failure_feedback,
            "original_output": history.get(step_id, {}),
        }

        # 跑 agent (传入 tracer 让 agent 自己写 success/fail trace)
        result: AgentResult = await agent.run(ctx, tracer=tracer)

        # 处理结果
        await self._handle_agent_result(task_id, step_id, result, payload, tracer)

    async def _handle_agent_result(
        self,
        task_id: str,
        step_id: str,
        result: AgentResult,
        payload: Dict[str, Any],
        tracer: Tracer,
    ):
        """根据 result.success 决定下一步"""
        if result.success:
            await self._on_step_success(task_id, step_id, result, payload, tracer)
        else:
            await self._on_step_failure(task_id, step_id, result, payload, tracer)

    async def _on_step_success(
        self,
        task_id: str,
        step_id: str,
        result: AgentResult,
        payload: Dict[str, Any],
        tracer: Tracer,
    ):
        """step 成功 -> 写库 -> 推进状态 -> 派下一个 step"""
        # 写 task_step
        with session_scope() as db:
            step = (
                db.query(TaskStep)
                .filter(TaskStep.task_id == task_id, TaskStep.step_id == step_id)
                .first()
            )
            if step:
                step.status = StepStatus.SUCCESS.value
                step.output_payload = result.output
                step.input_payload = {"payload": payload.get("payload", {}), "attempt": payload.get("attempt", 1)}
                step.latency_ms = result.latency_ms
                step.token_cost = result.input_tokens + result.output_tokens
                step.model_name = result.model
                step.prompt_version = result.prompt_version
                step.finished_at = __import__("datetime").datetime.utcnow()

        # 注：step.success trace 已由 agent.run() 内部写入
        # 这里只写 task_step 状态推进，trace 不重复写

        # 更新 payload.history
        history = dict(payload.get("history", {}))
        history[step_id] = result.output

        # 如果是 quality_evaluation，进入评估分支
        if step_id == "quality_evaluation":
            await self._handle_evaluation(task_id, result.output, tracer)
            return

        # 否则推进到下一个 step
        nxt = next_step_or_done(step_id)
        if nxt is None:
            # 工作流结束
            await self._finalize_task(task_id, status=TaskStatus.SUCCESS.value)
            return

        # 派下一个 step
        # 把 history 通过 queue payload 透传
        next_payload = dict(payload)
        next_payload["history"] = history
        next_payload["attempt"] = 1
        await self.queue.publish_step(task_id, nxt, next_payload)

        # 任务状态 - 进入 evaluating / running 下一步
        self._transition_task(task_id, TaskStatus.RUNNING.value)

    async def _on_step_failure(
        self,
        task_id: str,
        step_id: str,
        result: AgentResult,
        payload: Dict[str, Any],
        tracer: Tracer,
    ):
        """step 失败 -> 写 failure -> 重试 or 进死信"""
        # 写失败原因到 step
        with session_scope() as db:
            step = (
                db.query(TaskStep)
                .filter(TaskStep.task_id == task_id, TaskStep.step_id == step_id)
                .first()
            )
            if step:
                step.status = StepStatus.FAILED.value
                step.failure_reason = result.failure_reason
                step.error_message = result.error_message
                step.finished_at = __import__("datetime").datetime.utcnow()
                step.retry_count = (step.retry_count or 0) + 1
                # 把失败时已消耗的 token / latency 也记上
                if result.latency_ms:
                    step.latency_ms = result.latency_ms
                if result.input_tokens or result.output_tokens:
                    step.token_cost = (result.input_tokens or 0) + (result.output_tokens or 0)
                if result.model:
                    step.model_name = result.model
                if result.prompt_version:
                    step.prompt_version = result.prompt_version

        # 注：step.fail trace 已由 agent.run() 内部写入
        # 这里只写 task_step 状态推进，trace 不重复写

        # 决定是 repair / retry / dead_letter
        new_retry_count = mark_task_retrying(task_id, result.failure_reason, result.error_message)
        max_retry = self._max_retry_of(task_id)

        # 评估类失败 → 触发 repair agent
        if result.failure_reason == FailureReason.JUDGE_REJECTED.value and result.repair_payload:
            await self._schedule_repair(task_id, step_id, result, payload)
            return

        if should_retry(new_retry_count, max_retry):
            # 重新派同一节点
            await self._schedule_retry(task_id, step_id, payload, new_retry_count, result)
            return

        # 进死信
        await self._schedule_dead_letter(task_id, step_id, result, payload)

    async def _schedule_retry(
        self,
        task_id: str,
        step_id: str,
        payload: Dict[str, Any],
        new_retry_count: int,
        result: AgentResult,
    ):
        """重新派同一 step，带上失败上下文"""
        # 计算 backoff 等待
        delay = compute_retry_delay(new_retry_count - 1)
        if delay > 0:
            logger.info(f"任务 {task_id} {step_id} 第 {new_retry_count} 次重试，延迟 {delay}s")

        async def _delayed_publish():
            await asyncio.sleep(delay)
            next_payload = dict(payload)
            next_payload["attempt"] = new_retry_count + 1
            next_payload["failure_feedback"] = (
                f"reason={result.failure_reason}, "
                f"error={result.error_message or ''}, "
                f"raw={result.raw_output[:300] if result.raw_output else ''}"
            )
            await self.queue.publish_step(task_id, step_id, next_payload)

        asyncio.create_task(_delayed_publish())

        # 推进任务状态
        self._transition_task(task_id, TaskStatus.RETRYING.value)

    async def _schedule_repair(
        self,
        task_id: str,
        step_id: str,
        result: AgentResult,
        payload: Dict[str, Any],
    ):
        """调度 repair agent 修复上游输出"""
        next_payload = dict(payload)
        next_payload["target_step"] = step_id
        next_payload["original_output"] = result.output or {}
        next_payload["failure_feedback"] = (
            result.repair_payload.get("error_details", [""])
            if isinstance(result.repair_payload.get("error_details"), list)
            else [str(result.repair_payload.get("error_details"))]
        )
        next_payload["attempt"] = 1
        await self.queue.publish_step(task_id, "repair", next_payload)
        self._transition_task(task_id, TaskStatus.RETRYING.value)

    async def _schedule_dead_letter(
        self,
        task_id: str,
        step_id: str,
        result: AgentResult,
        payload: Dict[str, Any],
    ):
        """进死信队列"""
        send_to_dead_letter(
            task_id=task_id,
            step_id=step_id,
            failure_reason=result.failure_reason or FailureReason.UNKNOWN_ERROR.value,
            input_payload=payload,
            last_output=result.raw_output or result.output,
            retry_count=self._retry_count_of(task_id),
            error_message=result.error_message or "",
        )
        await self.queue.publish_dead_letter(
            task_id,
            step_id,
            {
                "task_id": task_id,
                "step_id": step_id,
                "failure_reason": result.failure_reason,
                "retry_count": self._retry_count_of(task_id),
            },
        )

    async def _handle_evaluation(
        self,
        task_id: str, eval_output: Dict[str, Any], tracer: Tracer
    ):
        """处理质量评估节点的结果"""
        score = eval_output.get("score", 0)
        passed = eval_output.get("passed", False)
        risk = eval_output.get("risk_level", "low")
        issues = eval_output.get("issues", [])
        fix = eval_output.get("suggested_fix", "")

        # 写 evaluation_results
        with session_scope() as db:
            er = EvaluationResult(
                task_id=task_id,
                step_id="quality_evaluation",
                score=score,
                passed=passed,
                issues=issues,
                risk_level=risk,
                suggested_fix=fix,
                evaluator_model="MiniMax-M3",
                prompt_version="v1.0",
            )
            db.add(er)

        # 任务进入 evaluating
        self._transition_task(task_id, TaskStatus.EVALUATING.value)

        if passed and risk != "high":
            await self._finalize_task(task_id, status=TaskStatus.SUCCESS.value, score=score)
            return

        # 评估不过 → 进人工审核 OR 触发修复 agent
        if score < 40 or risk == "high":
            await self._finalize_task(task_id, status=TaskStatus.MANUAL_REVIEW.value, score=score)
            return

        # 评分 40-70 → 进人工 / 重试
        await self._schedule_task_retry_after_eval(
            task_id, score, issues, fix, tracer
        )

    async def _schedule_task_retry_after_eval(
        self, task_id, score, issues, fix, tracer
    ):
        """评估未通过 → 重新派 script_generation 并带上反馈"""
        # 重新跑 script_generation 节点
        with session_scope() as db:
            history = self._collect_history(db, task_id)
            product = self._product_of(task_id)
            trace_id = self._trace_id_of(task_id)

        feedback_str = f"score={score}\nissues={issues}\nsuggested_fix={fix}"
        next_payload = {
            "task_id": task_id,
            "trace_id": trace_id,
            "product": product,
            "history": history,
            "attempt": 1,
            "failure_feedback": feedback_str,
        }
        await self.queue.publish_step(task_id, "script_generation", next_payload)
        self._transition_task(task_id, TaskStatus.RETRYING.value)

    async def _finalize_task(
        self,
        task_id: str,
        status: str = TaskStatus.SUCCESS.value,
        score: Optional[int] = None,
    ):
        """收尾任务"""
        with session_scope() as db:
            task = db.query(Task).filter(Task.task_id == task_id).first()
            if not task:
                return
            try:
                assert_transition_task(task.status, status)
            except Exception as e:
                logger.warning(f"非法最终状态转移: {task.status} -> {status}: {e}")
                return
            task.status = status
            task.finished_at = __import__("datetime").datetime.utcnow()
            if score is not None:
                # 评分附加到 output_payload
                op = task.output_payload or {}
                op["quality_score"] = score
                task.output_payload = op

        tracer = Tracer(self._trace_id_of(task_id))
        tracer.record(
            task_id=task_id,
            event_type="task.finalize",
            event_status=status,
        )

    # ============================================================
    # 内部 helper
    # ============================================================
    def _transition_task(self, task_id: str, to_status: str):
        try:
            with session_scope() as db:
                t = db.query(Task).filter(Task.task_id == task_id).first()
                if not t:
                    return
                try:
                    assert_transition_task(t.status, to_status)
                except Exception:
                    logger.warning(f"任务 {task_id} 非法转移 {t.status} -> {to_status}")
                    return
                t.status = to_status
        except Exception as e:
            logger.error(f"_transition_task 失败: {e}")

    def _transition_step(self, task_id: str, step_id: str, to_status: str):
        try:
            with session_scope() as db:
                s = (
                    db.query(TaskStep)
                    .filter(TaskStep.task_id == task_id, TaskStep.step_id == step_id)
                    .first()
                )
                if not s:
                    return
                try:
                    assert_transition_step(s.status, to_status)
                except Exception:
                    logger.warning(f"step {task_id}/{step_id} 非法转移 {s.status} -> {to_status}")
                    return
                s.status = to_status
                s.started_at = __import__("datetime").datetime.utcnow()
        except Exception as e:
            logger.error(f"_transition_step 失败: {e}")

    def _max_retry_of(self, task_id: str) -> int:
        with session_scope() as db:
            t = db.query(Task).filter(Task.task_id == task_id).first()
            return t.max_retry if t else settings.max_retry_count

    def _retry_count_of(self, task_id: str) -> int:
        with session_scope() as db:
            t = db.query(Task).filter(Task.task_id == task_id).first()
            return t.retry_count if t else 0

    def _trace_id_of(self, task_id: str) -> str:
        with session_scope() as db:
            t = db.query(Task).filter(Task.task_id == task_id).first()
            return t.trace_id if t else ""

    def _product_of(self, task_id: str) -> Dict[str, Any]:
        with session_scope() as db:
            t = db.query(Task).filter(Task.task_id == task_id).first()
            return t.input_payload if t else {}

    def _collect_history(self, db, task_id: str) -> Dict[str, Any]:
        steps = db.query(TaskStep).filter(TaskStep.task_id == task_id).all()
        hist = {}
        for s in steps:
            if s.output_payload:
                hist[s.step_id] = s.output_payload
        return hist


# 单例
_orch: Optional[WorkflowOrchestrator] = None


def get_orchestrator() -> WorkflowOrchestrator:
    global _orch
    if _orch is None:
        _orch = WorkflowOrchestrator()
    return _orch
