"""Trace API - 按 trace_id 或 task_id 拉取全链路事件"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db.database import get_db
from app.models.trace import TaskTrace

router = APIRouter()


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
