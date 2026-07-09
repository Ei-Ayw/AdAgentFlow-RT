"""DeadLetter ORM - 死信队列"""
from sqlalchemy import Column, BigInteger, String, Integer, Text, Boolean, DateTime
from sqlalchemy.sql import func
from app.db.database import Base
from app.db.types import JSONBCompat


class DeadLetter(Base):
    __tablename__ = "dead_letters"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    task_id = Column(String(64), index=True)
    step_id = Column(String(64))
    failure_reason = Column(String(128))
    input_payload = Column(JSONBCompat)
    last_output = Column(JSONBCompat)
    retry_count = Column(Integer)
    error_message = Column(Text)
    resolved = Column(Boolean, default=False, index=True)
    resolved_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
