"""任务提交 / 查询 API"""
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing import List, Optional
import asyncio

from app.core.logging import get_logger
from app.db.database import get_db
from app.models.task import Task
from app.models.step import TaskStep
from app.models.execution import StepExecution
from app.services.orchestrator import get_orchestrator
from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = get_logger()
router = APIRouter()


class SubmitTaskRequest(BaseModel):
    """提交任务请求体"""

    product_name: str = Field(
        ..., min_length=1, max_length=255,
        json_schema_extra={"example": "Portable Neck Fan"},
    )
    target_user: Optional[str] = Field(
        "", max_length=255,
        json_schema_extra={"example": "commuters and outdoor workers"},
    )
    selling_points: List[str] = Field(
        default_factory=lambda: ["hands-free cooling", "long battery life"],
        min_length=1,
        max_length=20,
    )
    platform: str = Field(
        "TikTok", min_length=1, max_length=64,
        json_schema_extra={"example": "TikTok"},
    )
    style: str = Field(
        "dramatic before-after ad", max_length=128,
        json_schema_extra={"example": "dramatic before-after ad"},
    )
    duration: int = Field(15, ge=5, le=60)
    product_assets: List[str] = Field(default_factory=list, max_length=12)
    reference_video: Optional[str] = Field(None, max_length=512)
    # 反馈重生: 非空时, 把该 task 的 evaluation 反馈带入新任务
    feedback_for_task_id: Optional[str] = Field(
        None, description="若不为空, 把该 task 的 evaluation 反馈带入新任务"
    )
    style_override: Optional[str] = Field(
        None, max_length=128, description="重生时强制覆盖 style"
    )

    @field_validator("product_name", "platform")
    @classmethod
    def non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空白字符串")
        return value

    @field_validator("selling_points")
    @classmethod
    def validate_selling_points(cls, values: List[str]) -> List[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("selling_points 不能包含空字符串")
        if any(len(value) > 200 for value in cleaned):
            raise ValueError("单条 selling_point 不能超过 200 字符")
        return cleaned


class SubmitTaskResponse(BaseModel):
    task_id: str
    trace_id: str
    status: str
    message: str = "任务已提交，请用 task_id 轮询进度"


@router.post("/submit", response_model=SubmitTaskResponse)
async def submit_task(
    req: SubmitTaskRequest,
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Header(
        None, alias="Idempotency-Key", min_length=8, max_length=128
    ),
):
    """提交广告生成任务

    Returns:
        task_id 用于查询
    """
    product = req.model_dump()
    if idempotency_key:
        existing = db.query(Task).filter(Task.request_id == idempotency_key).first()
        if existing:
            return SubmitTaskResponse(
                task_id=existing.task_id,
                trace_id=existing.trace_id or "",
                status=existing.status,
            )
    orch = get_orchestrator()
    try:
        task_id = await orch.create_task(product, request_id=idempotency_key)
    except IntegrityError:
        db.rollback()
        existing = db.query(Task).filter(Task.request_id == idempotency_key).first()
        if not existing:
            raise
        return SubmitTaskResponse(
            task_id=existing.task_id,
            trace_id=existing.trace_id or "",
            status=existing.status,
        )
    # 从 DB 拿 trace_id
    task = db.query(Task).filter(Task.task_id == task_id).first()
    return SubmitTaskResponse(
        task_id=task_id,
        trace_id=task.trace_id if task else "",
        status="queued",
    )


class StepStatus(BaseModel):
    step_id: str
    step_name: str
    status: str
    retry_count: int
    failure_reason: Optional[str] = None
    error_message: Optional[str] = None
    output_payload: Optional[dict] = None
    latency_ms: Optional[int] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class TaskDetailResponse(BaseModel):
    task_id: str
    trace_id: Optional[str]
    status: str
    product_name: Optional[str]
    platform: Optional[str]
    style: Optional[str]
    duration: Optional[int]
    retry_count: int
    last_failure_reason: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]
    finished_at: Optional[str]
    selling_points: Optional[List[str]] = None
    target_user: Optional[str] = None
    product_assets: List[str] = Field(default_factory=list)
    reference_video: Optional[str] = None
    steps: List[StepStatus] = []
    output_payload: Optional[dict] = None


class StepExecutionResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    execution_id: str
    step_id: str
    run_number: int
    attempt: int
    status: str
    input_payload: Optional[dict] = None
    output_payload: Optional[dict] = None
    failure_reason: Optional[str] = None
    error_message: Optional[str] = None
    model_name: Optional[str] = None
    prompt_version: Optional[str] = None
    input_tokens: int
    output_tokens: int
    latency_ms: int
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


@router.get("/{task_id}", response_model=TaskDetailResponse)
def get_task(task_id: str, db: Session = Depends(get_db)):
    """查询任务详情 + 节点状态"""
    task = db.query(Task).filter(Task.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    steps = (
        db.query(TaskStep)
        .filter(TaskStep.task_id == task_id)
        .order_by(TaskStep.id.asc())
        .all()
    )
    return TaskDetailResponse(
        task_id=task.task_id,
        trace_id=task.trace_id,
        status=task.status,
        product_name=task.product_name,
        platform=task.platform,
        style=task.style,
        duration=task.duration,
        retry_count=task.retry_count or 0,
        last_failure_reason=task.last_failure_reason,
        selling_points=task.selling_points or [],
        target_user=task.target_user,
        product_assets=(task.input_payload or {}).get("product_assets", []),
        reference_video=(task.input_payload or {}).get("reference_video"),
        created_at=task.created_at.isoformat() if task.created_at else None,
        updated_at=task.updated_at.isoformat() if task.updated_at else None,
        finished_at=task.finished_at.isoformat() if task.finished_at else None,
        steps=[
            StepStatus(
                step_id=s.step_id,
                step_name=s.step_name or "",
                status=s.status or "",
                retry_count=s.retry_count or 0,
                failure_reason=s.failure_reason,
                error_message=s.error_message,
                output_payload=s.output_payload,
                latency_ms=s.latency_ms,
                started_at=s.started_at.isoformat() if s.started_at else None,
                finished_at=s.finished_at.isoformat() if s.finished_at else None,
            )
            for s in steps
        ],
        output_payload=task.output_payload,
    )


@router.get("/{task_id}/executions", response_model=List[StepExecutionResponse])
def list_step_executions(
    task_id: str,
    step_id: Optional[str] = Query(None, max_length=64),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """按运行版本返回节点执行历史，便于审计重试与 Repair。"""
    if not db.query(Task.id).filter(Task.task_id == task_id).first():
        raise HTTPException(status_code=404, detail="Task not found")
    query = db.query(StepExecution).filter(StepExecution.task_id == task_id)
    if step_id:
        query = query.filter(StepExecution.step_id == step_id)
    rows = query.order_by(StepExecution.id.desc()).limit(limit).all()
    return [
        StepExecutionResponse(
            execution_id=row.execution_id,
            step_id=row.step_id,
            run_number=row.run_number,
            attempt=row.attempt,
            status=row.status,
            input_payload=row.input_payload,
            output_payload=row.output_payload,
            failure_reason=row.failure_reason,
            error_message=row.error_message,
            model_name=row.model_name,
            prompt_version=row.prompt_version,
            input_tokens=row.input_tokens or 0,
            output_tokens=row.output_tokens or 0,
            latency_ms=row.latency_ms or 0,
            started_at=row.started_at.isoformat() if row.started_at else None,
            finished_at=row.finished_at.isoformat() if row.finished_at else None,
        )
        for row in rows
    ]


@router.get("/")
def list_tasks(
    status: Optional[str] = Query(None, description="任务状态过滤"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """列出任务"""
    q = db.query(Task)
    if status:
        q = q.filter(Task.status == status)
    total = q.count()
    rows = q.order_by(Task.id.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "task_id": r.task_id,
                "status": r.status,
                "product_name": r.product_name,
                "platform": r.platform,
                "duration": r.duration,
                "retry_count": r.retry_count,
                "last_failure_reason": r.last_failure_reason,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in rows
        ],
    }
