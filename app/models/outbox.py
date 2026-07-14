"""Transactional Outbox：将待发布消息与业务状态放在同一数据库事务。"""
import uuid

from sqlalchemy import Column, DateTime, Index, Integer, String, Text
from sqlalchemy.sql import func

from app.db.database import Base
from app.db.types import JSONBCompat


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_status_available", "status", "available_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(
        String(64), unique=True, nullable=False, index=True,
        default=lambda: uuid.uuid4().hex,
    )
    event_type = Column(String(64), nullable=False, default="step.dispatch")
    task_id = Column(String(64), nullable=False, index=True)
    step_id = Column(String(64), nullable=False)
    payload = Column(JSONBCompat, nullable=False)
    delay_seconds = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    lock_owner = Column(String(64))
    locked_at = Column(DateTime(timezone=True))
    available_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    published_at = Column(DateTime(timezone=True))
    last_error = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
