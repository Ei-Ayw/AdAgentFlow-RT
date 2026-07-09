"""TaskTrace ORM - 全链路追踪事件"""
from sqlalchemy import Column, BigInteger, String, Integer, DateTime, Text
from sqlalchemy.sql import func
from app.db.database import Base
from app.db.types import JSONBCompat


class TaskTrace(Base):
    __tablename__ = "task_traces"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    trace_id = Column(String(64), nullable=False, index=True)
    task_id = Column(String(64), index=True)
    step_id = Column(String(64))
    event_type = Column(String(64))  # step.start / step.success / step.fail / llm.call / etc.
    event_status = Column(String(32))
    latency_ms = Column(Integer)
    model_name = Column(String(128))
    prompt_version = Column(String(64))
    token_cost = Column(Integer)
    error_message = Column(Text)
    extra_metadata = Column("metadata", JSONBCompat)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
