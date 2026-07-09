"""AgentMetric ORM - 节点级聚合指标 + MessageDedup"""
from sqlalchemy import (
    Column,
    BigInteger,
    String,
    Integer,
    DateTime,
    Boolean,
    UniqueConstraint,
)
from sqlalchemy.sql import func
from app.db.database import Base


class AgentMetric(Base):
    """每个 step_name 的聚合指标 - O(1) 查询 Dashboard"""

    __tablename__ = "agent_metrics"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    step_name = Column(String(128), unique=True, nullable=False)
    total_executions = Column(BigInteger, default=0)
    success_executions = Column(BigInteger, default=0)
    failed_executions = Column(BigInteger, default=0)
    retry_executions = Column(BigInteger, default=0)
    total_latency_ms = Column(BigInteger, default=0)
    total_token_cost = Column(BigInteger, default=0)
    json_failures = Column(BigInteger, default=0)
    schema_failures = Column(BigInteger, default=0)
    last_updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MessageDedup(Base):
    """消息去重记录 - DB 兜底，Redis 的额外保险"""

    __tablename__ = "message_dedup_records"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    message_id = Column(String(128), unique=True, nullable=False)
    task_id = Column(String(64), index=True)
    step_id = Column(String(64))
    consumed_at = Column(DateTime(timezone=True), server_default=func.now())
