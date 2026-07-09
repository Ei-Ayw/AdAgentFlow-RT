"""死信任务 API"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from app.db.database import get_db
from app.models.dead_letter import DeadLetter
from app.services.orchestrator import get_orchestrator
from pydantic import BaseModel

router = APIRouter()


class DeadLetterItem(BaseModel):
    id: int
    task_id: str
    step_id: Optional[str]
    failure_reason: Optional[str]
    retry_count: Optional[int]
    error_message: Optional[str]
    resolved: bool
    created_at: Optional[str]


class DeadLetterListResponse(BaseModel):
    total: int
    items: List[DeadLetterItem]


@router.get("/", response_model=DeadLetterListResponse)
def list_dead_letters(
    resolved: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(DeadLetter)
    if resolved is not None:
        q = q.filter(DeadLetter.resolved == resolved)
    total = q.count()
    rows = q.order_by(DeadLetter.id.desc()).offset(offset).limit(limit).all()
    return DeadLetterListResponse(
        total=total,
        items=[
            DeadLetterItem(
                id=r.id,
                task_id=r.task_id,
                step_id=r.step_id,
                failure_reason=r.failure_reason,
                retry_count=r.retry_count,
                error_message=r.error_message,
                resolved=r.resolved or False,
                created_at=r.created_at.isoformat() if r.created_at else None,
            )
            for r in rows
        ],
    )


@router.get("/{dl_id}")
def get_dead_letter(dl_id: int, db: Session = Depends(get_db)):
    dl = db.query(DeadLetter).filter(DeadLetter.id == dl_id).first()
    if not dl:
        raise HTTPException(404, "Dead letter not found")
    return {
        "id": dl.id,
        "task_id": dl.task_id,
        "step_id": dl.step_id,
        "failure_reason": dl.failure_reason,
        "input_payload": dl.input_payload,
        "last_output": dl.last_output,
        "retry_count": dl.retry_count,
        "error_message": dl.error_message,
        "resolved": dl.resolved,
        "created_at": dl.created_at.isoformat() if dl.created_at else None,
    }


@router.post("/{task_id}/resume")
async def resume_dead_letter(task_id: str, db: Session = Depends(get_db)):
    """人工接管死信任务，重新派发"""
    orch = get_orchestrator()
    ok = await orch.resume_dead_letter(task_id)
    if not ok:
        raise HTTPException(400, "任务不在 dead_letter 状态或不存在")

    # 标记死信已 resolved
    dl_list = db.query(DeadLetter).filter(
        DeadLetter.task_id == task_id,
        DeadLetter.resolved == False,
    ).all()
    for dl in dl_list:
        dl.resolved = True
        dl.resolved_at = datetime.utcnow()

    return {"task_id": task_id, "status": "queued", "message": "已重新派发到队列"}


@router.post("/{dl_id}/resolve")
def mark_resolved(dl_id: int, db: Session = Depends(get_db)):
    dl = db.query(DeadLetter).filter(DeadLetter.id == dl_id).first()
    if not dl:
        raise HTTPException(404, "Dead letter not found")
    dl.resolved = True
    dl.resolved_at = datetime.utcnow()
    return {"id": dl.id, "resolved": True}
