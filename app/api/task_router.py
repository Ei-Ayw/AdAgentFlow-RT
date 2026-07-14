"""任务提交 / 查询 API"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import asyncio

from app.core.logging import get_logger
from app.db.database import get_db
from app.models.task import Task
from app.models.step import TaskStep
from app.services.orchestrator import get_orchestrator
from pydantic import BaseModel, Field

logger = get_logger()
router = APIRouter()


class SubmitTaskRequest(BaseModel):
    """提交任务请求体"""

    product_name: str = Field(..., example="Portable Neck Fan")
    target_user: Optional[str] = Field("", example="commuters and outdoor workers")
    selling_points: List[str] = Field(
        default_factory=lambda: ["hands-free cooling", "long battery life"],
    )
    platform: str = Field("TikTok", example="TikTok")
    style: str = Field("dramatic before-after ad", example="dramatic before-after ad")
    duration: int = Field(15, ge=5, le=60)
    # 反馈重生: 非空时, 把该 task 的 evaluation 反馈带入新任务
    feedback_for_task_id: Optional[str] = Field(
        None, description="若不为空, 把该 task 的 evaluation 反馈带入新任务"
    )
    style_override: Optional[str] = Field(
        None, description="重生时强制覆盖 style"
    )


class SubmitTaskResponse(BaseModel):
    task_id: str
    trace_id: str
    status: str
    message: str = "任务已提交，请用 task_id 轮询进度"


@router.post("/submit", response_model=SubmitTaskResponse)
async def submit_task(req: SubmitTaskRequest, db: Session = Depends(get_db)):
    """提交广告生成任务

    Returns:
        task_id 用于查询
    """
    product = req.model_dump()
    orch = get_orchestrator()
    task_id = await orch.create_task(product)
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
    steps: List[StepStatus] = []
    output_payload: Optional[dict] = None


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
                latency_ms=s.latency_ms,
                started_at=s.started_at.isoformat() if s.started_at else None,
                finished_at=s.finished_at.isoformat() if s.finished_at else None,
            )
            for s in steps
        ],
        output_payload=task.output_payload,
    )


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
