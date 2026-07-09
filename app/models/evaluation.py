"""EvaluationResult ORM - LLM-as-Judge 结果"""
from sqlalchemy import Column, BigInteger, String, Integer, DateTime, Text, Boolean
from sqlalchemy.sql import func
from app.db.database import Base
from app.db.types import JSONBCompat


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    task_id = Column(String(64), nullable=False, index=True)
    step_id = Column(String(64))
    score = Column(Integer)
    passed = Column(Boolean, index=True)
    issues = Column(JSONBCompat)
    risk_level = Column(String(32))
    suggested_fix = Column(Text)
    evaluator_model = Column(String(128))
    prompt_version = Column(String(64))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
