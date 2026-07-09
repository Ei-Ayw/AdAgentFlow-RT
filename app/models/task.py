"""Task ORM - 任务主表"""
from sqlalchemy import Column, BigInteger, String, Integer, DateTime, Text
from sqlalchemy.sql import func
from app.db.database import Base
from app.db.types import JSONBCompat


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    task_id = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(String(32), nullable=False, default="created", index=True)
    product_name = Column(String(255))
    platform = Column(String(64))
    style = Column(String(128))
    duration = Column(Integer)
    target_user = Column(String(255))
    selling_points = Column(JSONBCompat, default=list)
    input_payload = Column(JSONBCompat)
    output_payload = Column(JSONBCompat)
    retry_count = Column(Integer, default=0)
    max_retry = Column(Integer, default=3)
    trace_id = Column(String(64), index=True)
    last_failure_reason = Column(String(128))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    finished_at = Column(DateTime(timezone=True))
