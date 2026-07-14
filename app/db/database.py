"""SQLAlchemy 数据库连接"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from contextlib import contextmanager
from app.core.config import settings


connect_args = None
if settings.database_url.startswith("postgresql"):
    connect_args = {
        "connect_timeout": settings.db_connect_timeout,
        "options": f"-c statement_timeout={settings.db_statement_timeout_ms}",
    }

# ============================================================
# Engine + Session
# ============================================================
engine = create_engine(
    # 数据库连接 URL
    settings.database_url,

    # 连接池中常驻保留的连接数
    pool_size=settings.db_pool_size,

    # 连接池满了以后，允许额外临时创建的连接数
    max_overflow=settings.db_max_overflow,

    # 每次从池中取连接前先检查连接是否可用，避免拿到失效连接
    pool_pre_ping=True,

    # 连接存活时间上限，超过 30 分钟就回收重建，防止长连接失效
    pool_recycle=1800,  # 30 分钟回收连接

    # 是否打印执行的 SQL 语句，False 表示不输出
    echo=False,

    # 使用 SQLAlchemy 新版行为模式
    future=True,

    # 池耗尽时有界失败，避免请求无限等待；PostgreSQL 同时限制连接和语句时长。
    pool_timeout=settings.db_pool_timeout,
    **({"connect_args": connect_args} if connect_args else {}),
)

# 创建一个“数据库会话工厂”。
# 之后每次调用 SessionLocal()，都会得到一个新的 Session 对象，用来执行查询、插入、更新、删除。
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False, # 不自动把未提交的修改提前刷到数据库。
    autocommit=False, # 不自动提交事务
    expire_on_commit=False, # commit() 之后，不自动让对象失效
    future=True,
)

# 创建 ORM 的基类。
# 以后你定义表模型时，一般都会继承它：
Base = declarative_base()


def get_db() -> Session:
    """FastAPI 依赖注入用"""
    # 创建一个新的数据库会话
    db = SessionLocal()
    try:
        # 把会话交给 FastAPI 的依赖系统使用
        yield db
    finally:
        # 请求结束后，无论成功还是失败都关闭连接
        db.close()


# 给普通 with 代码块用，自动 commit / rollback / close
@contextmanager
def session_scope():
    """通用 with-context ，可配合 try/except 显式 commit/rollback"""
    db = SessionLocal()
    try:
        # 交给 with 代码块使用
        yield db
        # 正常结束时提交事务
        db.commit()
    except Exception:
        # 出错时回滚事务，避免脏数据写入
        db.rollback()
        # 把异常继续抛出去，交给上层处理
        raise
    finally:
        # 不管成功失败，最后都关闭会话
        db.close()


def init_db():
    """启动时调用 - CREATE TABLE IF NOT EXISTS"""
        # 显式导入所有模型，让 SQLAlchemy 把表结构注册到 Base.metadata
    from app.models import (  # noqa
        task, step, trace, dead_letter, evaluation, metric, outbox, execution,
    )

    # 根据已注册的模型，创建所有不存在的表
    Base.metadata.create_all(bind=engine)
