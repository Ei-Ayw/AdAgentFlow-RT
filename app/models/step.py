"""TaskStep ORM - 节点级状态表"""
from sqlalchemy import (
    Column,
    BigInteger,
    String,
    Integer,
    DateTime,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func
from app.db.database import Base
from app.db.types import JSONBCompat


class TaskStep(Base):
    __tablename__ = "task_steps"
    __table_args__ = (UniqueConstraint("task_id", "step_id", name="uq_task_step"),)

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    task_id = Column(String(64), nullable=False, index=True)
    step_id = Column(String(64), nullable=False)
    step_name = Column(String(128))
    status = Column(String(32), default="pending", index=True)
    input_payload = Column(JSONBCompat)
    output_payload = Column(JSONBCompat)
    retry_count = Column(Integer, default=0)
    failure_reason = Column(String(128))
    error_message = Column(Text)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    latency_ms = Column(Integer)
    token_cost = Column(Integer, default=0)
    model_name = Column(String(128))
    prompt_version = Column(String(64))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
