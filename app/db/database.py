"""SQLAlchemy 数据库连接"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from contextlib import contextmanager
from app.core.config import settings

# ============================================================
# Engine + Session
# ============================================================
engine = create_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
    pool_recycle=1800,  # 30 分钟回收连接
    echo=False,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)

Base = declarative_base()


def get_db() -> Session:
    """FastAPI 依赖注入用"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope():
    """通用 with-context ，可配合 try/except 显式 commit/rollback"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """启动时调用 - CREATE TABLE IF NOT EXISTS"""
    # 强制 import models 让 SQLAlchemy 注册
    from app.models import task, step, trace, dead_letter, evaluation, metric  # noqa
    Base.metadata.create_all(bind=engine)
