"""StepExecution：记录节点每一次真实执行，TaskStep 仅保留当前快照。"""
import uuid

from sqlalchemy import Column, DateTime, Index, Integer, String, Text
from sqlalchemy.sql import func

from app.db.database import Base
from app.db.types import JSONBCompat


class StepExecution(Base):
    __tablename__ = "step_executions"
    __table_args__ = (
        Index(
            "ix_step_execution_task_step",
            "task_id",
            "step_id",
            "run_number",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    execution_id = Column(
        String(64), unique=True, nullable=False, index=True,
        default=lambda: uuid.uuid4().hex,
    )
    task_id = Column(String(64), nullable=False, index=True)
    step_id = Column(String(64), nullable=False)
    run_number = Column(Integer, nullable=False)
    attempt = Column(Integer, nullable=False, default=1)
    status = Column(String(32), nullable=False, default="running", index=True)
    input_payload = Column(JSONBCompat)
    output_payload = Column(JSONBCompat)
    failure_reason = Column(String(128))
    error_message = Column(Text)
    model_name = Column(String(128))
    prompt_version = Column(String(64))
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    latency_ms = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at = Column(DateTime(timezone=True))
