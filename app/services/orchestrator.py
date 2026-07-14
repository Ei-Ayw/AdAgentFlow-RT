"""工作流编排器 - 控制 step 链式执行 + 任务状态机推进"""
import time
import asyncio
import json
import datetime
import uuid
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
from app.models.execution import StepExecution
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
from app.services.idempotency import acquire_idempotent, release_idempotent
from app.services.outbox import enqueue_step_event, try_publish_event

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
    async def create_task(
        self, product: Dict[str, Any], request_id: Optional[str] = None
    ) -> str:
        """接收新商品信息，写库，推入队列。

        支持反馈重生:
        - product.feedback_for_task_id 非空 → 从 script_generation 起跑,
          payload.failure_feedback 包含上次的 score/issues/suggested_fix
        - product.style_override 非空 → 覆盖 product.style
        """
        from app.services.tracing import generate_task_id

        # 1. 反馈上下文准备
        feedback_for_task_id = product.get("feedback_for_task_id")
        style_override = product.get("style_override")
        feedback_str = ""
        history_override: Dict[str, Any] = {}
        start_step = WORKFLOW_STEPS[0]

        if feedback_for_task_id:
            with session_scope() as db:
                ev = (
                    db.query(EvaluationResult)
                    .filter(EvaluationResult.task_id == feedback_for_task_id)
                    .order_by(EvaluationResult.id.desc())
                    .first()
                )
            if ev:
                issues_text = "\n".join(
                    (i.get("detail") if isinstance(i, dict) else str(i))
                    for i in (ev.issues or [])
                )
                feedback_str = (
                    f"score={ev.score}\n"
                    f"issues={issues_text}\n"
                    f"suggested_fix={ev.suggested_fix or ''}"
                )
            # 收集上次的 product_analysis 输出作为 history
            with session_scope() as db:
                hist_step = (
                    db.query(TaskStep)
                    .filter(
                        TaskStep.task_id == feedback_for_task_id,
                        TaskStep.step_id == "product_analysis",
                    )
                    .first()
                )
            if hist_step and hist_step.output_payload:
                history_override["product_analysis"] = hist_step.output_payload
            start_step = "script_generation"

        if style_override:
            product = {**product, "style": style_override}

        # 2. 正常入库
        task_id = generate_task_id()
        trace_id = generate_trace_id()

        with session_scope() as db:
            t = Task(
                task_id=task_id,
                request_id=request_id,
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
            for step_id in [*WORKFLOW_STEPS, "repair"]:
                step = TaskStep(
                    task_id=task_id,
                    step_id=step_id,
                    step_name=STEP_NAME_DISPLAY.get(step_id, step_id),
                    status=StepStatus.PENDING.value,
                )
                db.add(step)
            first_event = enqueue_step_event(
                db,
                task_id=task_id,
                step_id=start_step,
                payload={
                    "task_id": task_id,
                    "trace_id": trace_id,
                    "product": product,
                    "history": history_override,
                    "attempt": 1,
                    **({"failure_feedback": feedback_str} if feedback_str else {}),
                },
            )

        await try_publish_event(first_event, self.queue)
        logger.info(
            f"任务已创建并派发: task_id={task_id}, trace_id={trace_id}, "
            f"start_step={start_step}"
        )
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
                s.output_payload = None
                s.failure_reason = None
                s.error_message = None
                s.started_at = None
                s.finished_at = None
            resume_event = enqueue_step_event(
                db,
                task_id=task_id,
                step_id=WORKFLOW_STEPS[0],
                payload={
                    "task_id": task_id,
                    "trace_id": task.trace_id,
                    "product": task.input_payload or {},
                    "history": {},
                    "attempt": 1,
                    "resumed_from_dead_letter": True,
                },
            )

        # 清理可能由异常退出遗留的执行租约。
        for step_id in [*WORKFLOW_STEPS, "repair"]:
            await release_idempotent(task_id, step_id)

        await try_publish_event(resume_event, self.queue)
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
        lock_owner = await acquire_idempotent(task_id, step_id)
        if not lock_owner:
            logger.warning(f"[{step_id}] {task_id} 已被持有，跳过重复消费")
            return
        try:
            # 已成功节点收到旧重复消息时直接返回；显式重跑会先把节点重置为 pending。
            if self._step_status_of(task_id, step_id) == StepStatus.SUCCESS.value:
                logger.info(f"[{step_id}] {task_id} 已成功，忽略重复消息")
                return

            # 推进任务和节点到 running。
            self._transition_task(task_id, TaskStatus.RUNNING.value)
            self._transition_step(task_id, step_id, StepStatus.RUNNING.value)

            agent = get_agent(step_id)
            ctx = {
                "task_id": task_id,
                "trace_id": trace_id,
                "product": product,
                "history": history,
                "attempt": attempt,
                "failure_feedback": failure_feedback,
                "original_output": payload.get("original_output", history.get(step_id, {})),
                "target_step": payload.get("target_step", ""),
            }

            execution_id = self._start_execution(task_id, step_id, payload)
            with logger.contextualize(execution_id=execution_id):
                try:
                    result: AgentResult = await agent.run(ctx, tracer=tracer)
                    await self._handle_agent_result(task_id, step_id, result, payload, tracer)
                    self._finish_execution(execution_id, result)
                except Exception as exc:
                    self._finish_execution_error(execution_id, exc)
                    raise
        finally:
            # 正常成功、业务失败和代码异常都释放；进程硬退出则依赖短租约恢复。
            try:
                await release_idempotent(task_id, step_id, lock_owner)
            except Exception as e:
                logger.error(f"释放执行锁失败 {task_id}/{step_id}: {e}")

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
        history = dict(payload.get("history", {}))
        history[step_id] = result.output
        next_event = None
        nxt = None if step_id in ("repair", "quality_evaluation") else next_step_or_done(step_id)
        next_payload = None
        if nxt is not None:
            next_payload = dict(payload)
            next_payload["history"] = history
            next_payload["attempt"] = 1

        # 节点成功状态与下一节点事件在同一事务提交。
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
                step.finished_at = datetime.datetime.now(datetime.timezone.utc)
            if nxt is not None and next_payload is not None:
                next_event = enqueue_step_event(
                    db,
                    task_id=task_id,
                    step_id=nxt,
                    payload=next_payload,
                )

        # 注：step.success trace 已由 agent.run() 内部写入
        # 这里只写 task_step 状态推进，trace 不重复写

        if step_id == "repair":
            await self._handle_repair_success(task_id, result.output or {}, payload, tracer)
            return

        # 如果是 quality_evaluation，进入评估分支
        if step_id == "quality_evaluation":
            await self._handle_evaluation(task_id, result.output, tracer)
            return

        if nxt is None:
            # 工作流结束
            await self._finalize_task(task_id, status=TaskStatus.SUCCESS.value)
            return

        await try_publish_event(next_event, self.queue)

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
                step.finished_at = datetime.datetime.now(datetime.timezone.utc)
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

        # JSON/Schema 自动修复仍失败时，交给独立 Repair Agent。
        if (
            result.needs_repair_agent
            and result.repair_payload
            and step_id in WORKFLOW_STEPS[:-1]
        ):
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

        next_payload = dict(payload)
        next_payload["attempt"] = new_retry_count + 1
        next_payload["failure_feedback"] = (
            f"reason={result.failure_reason}, "
            f"error={result.error_message or ''}, "
            f"raw={result.raw_output[:300] if result.raw_output else ''}"
        )
        with session_scope() as db:
            step = (
                db.query(TaskStep)
                .filter(TaskStep.task_id == task_id, TaskStep.step_id == step_id)
                .first()
            )
            if step:
                assert_transition_step(step.status, StepStatus.RETRYING.value)
                step.status = StepStatus.RETRYING.value
            retry_event = enqueue_step_event(
                db,
                task_id=task_id,
                step_id=step_id,
                payload=next_payload,
                delay_seconds=delay,
            )
        await try_publish_event(retry_event, self.queue)

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
        next_payload["original_output"] = result.repair_payload.get(
            "original_output", result.output or {}
        )
        next_payload["failure_feedback"] = (
            result.repair_payload.get("error_details", [""])
            if isinstance(result.repair_payload.get("error_details"), list)
            else [str(result.repair_payload.get("error_details"))]
        )
        next_payload["attempt"] = 1
        with session_scope() as db:
            repair_step = (
                db.query(TaskStep)
                .filter(TaskStep.task_id == task_id, TaskStep.step_id == "repair")
                .first()
            )
            if repair_step:
                self._clear_step_for_rerun(repair_step)
            repair_event = enqueue_step_event(
                db,
                task_id=task_id,
                step_id="repair",
                payload=next_payload,
            )
        await try_publish_event(repair_event, self.queue)

    async def _handle_repair_success(
        self,
        task_id: str,
        repaired_output: Dict[str, Any],
        payload: Dict[str, Any],
        tracer: Tracer,
    ) -> None:
        """将修复结果写回目标节点，使下游失效并从下一节点继续。"""
        target_step = payload.get("target_step", "")
        if target_step not in WORKFLOW_STEPS[:-1]:
            raise ValueError(f"不支持的修复目标节点: {target_step}")

        with session_scope() as db:
            target = (
                db.query(TaskStep)
                .filter(TaskStep.task_id == task_id, TaskStep.step_id == target_step)
                .first()
            )
            if not target:
                raise ValueError(f"修复目标节点不存在: {task_id}/{target_step}")
            target.status = StepStatus.SUCCESS.value
            target.output_payload = repaired_output
            target.failure_reason = None
            target.error_message = None
            target.finished_at = datetime.datetime.now(datetime.timezone.utc)

            target_idx = WORKFLOW_STEPS.index(target_step)
            for downstream_id in WORKFLOW_STEPS[target_idx + 1 :]:
                downstream = (
                    db.query(TaskStep)
                    .filter(TaskStep.task_id == task_id, TaskStep.step_id == downstream_id)
                    .first()
                )
                if downstream:
                    self._clear_step_for_rerun(downstream)

            history = self._collect_history(db, task_id)
            next_step = next_step_or_done(target_step)
            next_payload = dict(payload)
            next_payload.pop("target_step", None)
            next_payload.pop("original_output", None)
            next_payload["history"] = history
            next_payload["attempt"] = 1
            next_payload["failure_feedback"] = ""
            next_event = (
                enqueue_step_event(
                    db,
                    task_id=task_id,
                    step_id=next_step,
                    payload=next_payload,
                )
                if next_step is not None
                else None
            )

        if next_step is None:
            await self._finalize_task(task_id, status=TaskStatus.SUCCESS.value)
            return

        await try_publish_event(next_event, self.queue)
        self._transition_task(task_id, TaskStatus.RUNNING.value)
        tracer.record(
            task_id=task_id,
            event_type="repair.applied",
            event_status="success",
            step_id=target_step,
        )

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
        new_retry_count = mark_task_retrying(
            task_id,
            FailureReason.JUDGE_REJECTED.value,
            f"score={score}; suggested_fix={fix}",
        )
        if not should_retry(new_retry_count, self._max_retry_of(task_id)):
            await self._finalize_task(
                task_id, status=TaskStatus.MANUAL_REVIEW.value, score=score
            )
            return

        # 脚本变化会使分镜、素材和旧评估全部失效。
        with session_scope() as db:
            self._reset_from_step_in_session(db, task_id, "script_generation")
            history = self._collect_history(db, task_id)
            task = db.query(Task).filter(Task.task_id == task_id).first()
            product = task.input_payload if task else {}
            trace_id = task.trace_id if task else ""
            feedback_str = f"score={score}\nissues={issues}\nsuggested_fix={fix}"
            next_payload = {
                "task_id": task_id,
                "trace_id": trace_id,
                "product": product,
                "history": history,
                "attempt": 1,
                "failure_feedback": feedback_str,
            }
            eval_retry_event = enqueue_step_event(
                db,
                task_id=task_id,
                step_id="script_generation",
                payload=next_payload,
            )
        await try_publish_event(eval_retry_event, self.queue)

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
            if task.status != status:
                assert_transition_task(task.status, status)
            task.status = status
            task.finished_at = datetime.datetime.now(datetime.timezone.utc)
            outputs = self._collect_history(db, task_id)
            outputs.pop("repair", None)
            if score is not None:
                outputs["quality_score"] = score
            task.output_payload = outputs

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
        with session_scope() as db:
            task = db.query(Task).filter(Task.task_id == task_id).first()
            if not task:
                raise ValueError(f"任务不存在: {task_id}")
            if task.status == to_status:
                return True
            assert_transition_task(task.status, to_status)
            task.status = to_status
            return True

    def _transition_step(self, task_id: str, step_id: str, to_status: str):
        with session_scope() as db:
            step = (
                db.query(TaskStep)
                .filter(TaskStep.task_id == task_id, TaskStep.step_id == step_id)
                .first()
            )
            if not step:
                raise ValueError(f"节点不存在: {task_id}/{step_id}")
            if step.status == to_status:
                return True
            assert_transition_step(step.status, to_status)
            step.status = to_status
            if to_status == StepStatus.RUNNING.value:
                step.started_at = datetime.datetime.now(datetime.timezone.utc)
            return True

    def _max_retry_of(self, task_id: str) -> int:
        with session_scope() as db:
            t = db.query(Task).filter(Task.task_id == task_id).first()
            return t.max_retry if t else settings.max_retry_count

    def _retry_count_of(self, task_id: str) -> int:
        with session_scope() as db:
            t = db.query(Task).filter(Task.task_id == task_id).first()
            return t.retry_count if t else 0

    def _step_status_of(self, task_id: str, step_id: str) -> Optional[str]:
        with session_scope() as db:
            step = (
                db.query(TaskStep)
                .filter(TaskStep.task_id == task_id, TaskStep.step_id == step_id)
                .first()
            )
            return step.status if step else None

    def _start_execution(
        self, task_id: str, step_id: str, payload: Dict[str, Any]
    ) -> str:
        execution_id = uuid.uuid4().hex
        with session_scope() as db:
            # PostgreSQL 下锁住节点快照，避免多个重复消息并发计算出相同版本号。
            db.query(TaskStep).filter(
                TaskStep.task_id == task_id,
                TaskStep.step_id == step_id,
            ).with_for_update().first()
            previous_runs = (
                db.query(StepExecution)
                .filter(
                    StepExecution.task_id == task_id,
                    StepExecution.step_id == step_id,
                )
                .count()
            )
            db.add(
                StepExecution(
                    execution_id=execution_id,
                    task_id=task_id,
                    step_id=step_id,
                    run_number=previous_runs + 1,
                    attempt=int(payload.get("attempt", 1)),
                    status="running",
                    input_payload=payload,
                    started_at=datetime.datetime.now(datetime.timezone.utc),
                )
            )
        return execution_id

    def _finish_execution(self, execution_id: str, result: AgentResult) -> None:
        with session_scope() as db:
            execution = (
                db.query(StepExecution)
                .filter(StepExecution.execution_id == execution_id)
                .first()
            )
            if not execution:
                return
            execution.status = "success" if result.success else "failed"
            execution.output_payload = result.output
            execution.failure_reason = result.failure_reason
            execution.error_message = result.error_message
            execution.model_name = result.model
            execution.prompt_version = result.prompt_version
            execution.input_tokens = result.input_tokens
            execution.output_tokens = result.output_tokens
            execution.latency_ms = result.latency_ms
            execution.finished_at = datetime.datetime.now(datetime.timezone.utc)

    def _finish_execution_error(self, execution_id: str, exc: Exception) -> None:
        with session_scope() as db:
            execution = (
                db.query(StepExecution)
                .filter(StepExecution.execution_id == execution_id)
                .first()
            )
            if not execution:
                return
            execution.status = "failed"
            execution.failure_reason = FailureReason.UNKNOWN_ERROR.value
            execution.error_message = str(exc)[:2000]
            execution.finished_at = datetime.datetime.now(datetime.timezone.utc)

    @staticmethod
    def _clear_step_for_rerun(step: TaskStep) -> None:
        step.status = StepStatus.PENDING.value
        step.input_payload = None
        step.output_payload = None
        step.failure_reason = None
        step.error_message = None
        step.started_at = None
        step.finished_at = None
        step.latency_ms = None
        step.token_cost = 0

    def _reset_step(self, task_id: str, step_id: str) -> None:
        with session_scope() as db:
            step = (
                db.query(TaskStep)
                .filter(TaskStep.task_id == task_id, TaskStep.step_id == step_id)
                .first()
            )
            if step:
                self._clear_step_for_rerun(step)

    def _reset_from_step(self, task_id: str, start_step: str) -> None:
        with session_scope() as db:
            self._reset_from_step_in_session(db, task_id, start_step)

    def _reset_from_step_in_session(self, db, task_id: str, start_step: str) -> None:
        start_idx = WORKFLOW_STEPS.index(start_step)
        reset_ids = set(WORKFLOW_STEPS[start_idx:])
        steps = db.query(TaskStep).filter(TaskStep.task_id == task_id).all()
        for step in steps:
            if step.step_id in reset_ids:
                self._clear_step_for_rerun(step)

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
