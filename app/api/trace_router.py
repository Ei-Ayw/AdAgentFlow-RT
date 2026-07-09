"""Trace API - 按 trace_id 或 task_id 拉取全链路事件"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db.database import get_db
from app.models.task import Task
from app.models.step import TaskStep
from app.models.trace import TaskTrace
from app.models.evaluation import EvaluationResult

router = APIRouter()


def _iso(value):
    """datetime -> isoformat 安全转换"""
    return value.isoformat() if value else None


@router.get("/{trace_id}")
def get_trace(trace_id: str, db: Session = Depends(get_db)):
    rows = (
        db.query(TaskTrace)
        .filter(TaskTrace.trace_id == trace_id)
        .order_by(TaskTrace.id.asc())
        .all()
    )
    if not rows:
        raise HTTPException(404, "Trace not found")
    return {
        "trace_id": trace_id,
        "events": [
            {
                "id": r.id,
                "task_id": r.task_id,
                "step_id": r.step_id,
                "event_type": r.event_type,
                "event_status": r.event_status,
                "latency_ms": r.latency_ms,
                "model_name": r.model_name,
                "prompt_version": r.prompt_version,
                "token_cost": r.token_cost,
                "error_message": r.error_message,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/by-task/{task_id}")
def get_traces_by_task(task_id: str, db: Session = Depends(get_db)):
    rows = (
        db.query(TaskTrace)
        .filter(TaskTrace.task_id == task_id)
        .order_by(TaskTrace.id.asc())
        .all()
    )
    return {
        "task_id": task_id,
        "events": [
            {
                "id": r.id,
                "trace_id": r.trace_id,
                "step_id": r.step_id,
                "event_type": r.event_type,
                "event_status": r.event_status,
                "latency_ms": r.latency_ms,
                "model_name": r.model_name,
                "prompt_version": r.prompt_version,
                "token_cost": r.token_cost,
                "error_message": r.error_message,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/by-task/{task_id}/timeline")
def get_task_timeline(task_id: str, db: Session = Depends(get_db)):
    """任务全链路甘特图所需数据 - task + steps + traces + evaluations"""
    task = db.query(Task).filter(Task.task_id == task_id).first()
    if not task:
        raise HTTPException(404, "task not found")

    steps = (
        db.query(TaskStep)
        .filter(TaskStep.task_id == task_id)
        .order_by(TaskStep.created_at.asc(), TaskStep.id.asc())
        .all()
    )

    traces = (
        db.query(TaskTrace)
        .filter(TaskTrace.task_id == task_id)
        .order_by(TaskTrace.created_at.asc(), TaskTrace.id.asc())
        .all()
    )

    evaluations = (
        db.query(EvaluationResult)
        .filter(EvaluationResult.task_id == task_id)
        .order_by(EvaluationResult.created_at.asc(), EvaluationResult.id.asc())
        .all()
    )

    return {
        "task": {
            "task_id": task.task_id,
            "status": task.status,
            "product_name": task.product_name,
            "platform": task.platform,
            "style": task.style,
            "duration": task.duration,
            "retry_count": task.retry_count or 0,
            "max_retry": task.max_retry or 0,
            "last_failure_reason": task.last_failure_reason,
            "created_at": _iso(task.created_at),
            "updated_at": _iso(task.updated_at),
            "finished_at": _iso(task.finished_at),
        },
        "steps": [
            {
                "id": s.id,
                "step_id": s.step_id,
                "step_name": s.step_name,
                "status": s.status,
                "retry_count": s.retry_count or 0,
                "failure_reason": s.failure_reason,
                "error_message": s.error_message,
                "started_at": _iso(s.started_at),
                "finished_at": _iso(s.finished_at),
                "latency_ms": s.latency_ms or 0,
                "token_cost": s.token_cost or 0,
                "model_name": s.model_name,
                "prompt_version": s.prompt_version,
                "created_at": _iso(s.created_at),
            }
            for s in steps
        ],
        "traces": [
            {
                "id": t.id,
                "trace_id": t.trace_id,
                "step_id": t.step_id,
                "event_type": t.event_type,
                "event_status": t.event_status,
                "latency_ms": t.latency_ms or 0,
                "model_name": t.model_name,
                "prompt_version": t.prompt_version,
                "token_cost": t.token_cost or 0,
                "error_message": t.error_message,
                "created_at": _iso(t.created_at),
            }
            for t in traces
        ],
        "evaluations": [
            {
                "id": e.id,
                "step_id": e.step_id,
                "score": e.score,
                "passed": bool(e.passed) if e.passed is not None else None,
                "issues": e.issues,
                "risk_level": e.risk_level,
                "suggested_fix": e.suggested_fix,
                "evaluator_model": e.evaluator_model,
                "prompt_version": e.prompt_version,
                "created_at": _iso(e.created_at),
            }
            for e in evaluations
        ],
    }
