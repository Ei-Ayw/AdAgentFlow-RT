"""Shared pytest fixtures for AdAgentFlow unit tests.

Goals:
- Force USE_MOCK_LLM=true and point DATABASE_URL at a temporary SQLite file
  BEFORE any app.* module is imported (those modules instantiate engines at
  import time).
- Provide per-test DB schema reset so tests don't bleed state into each other.
- Provide a session-scoped mock_infra context, lazily initialised, that monkey-
  patches the orchestrator / queue / DB / LLM stack.

Note on SQLite + memory:
SQLite ":memory:" databases use `SingletonThreadPool` which is incompatible
with the `max_overflow` arg the production engine passes. We therefore point
the test DB at a unique file under tmp_path so SQLAlchemy can use the
`QueuePool` which accepts max_overflow.
"""
from __future__ import annotations

import os
import sys
import tempfile
import pathlib
import importlib
from pathlib import Path

import pytest

# ============================================================
# 1. 环境变量必须在任何 app.* 导入之前设置
# ============================================================
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_TMP_DB = pathlib.Path(tempfile.gettempdir()) / "adagentflow_test_default.db"
os.environ.setdefault("USE_MOCK_LLM", "true")
os.environ.setdefault("LANGFUSE_ENABLED", "false")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP_DB}")


# ============================================================
# 2. Pytest fixtures
# ============================================================
@pytest.fixture(scope="session", autouse=True)
def _force_mock_llm_env():
    """保证测试期间 settings.use_mock_llm == True。"""
    from app.core import config as cfg

    original = cfg.settings.use_mock_llm
    cfg.settings.use_mock_llm = True
    yield
    cfg.settings.use_mock_llm = original


@pytest.fixture()
def sqlite_db(tmp_path):
    """临时 SQLite DB，每个 test 一个全新 schema。

    之所以用 file 而不是 :memory:：SingletonThreadPool 不接受 max_overflow。
    """
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"

    # 改 settings.database_url（影响后续所有 session_scope / engine 创建）
    from app.core import config as cfg

    original_url = cfg.settings.database_url
    cfg.settings.database_url = db_url

    # 重新构造 engine（生产 engine 在 import 时已用 postgres url 创建，
    # 现在替换成 sqlite）
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import database as db_module

    original_engine = db_module.engine
    original_session_local = db_module.SessionLocal

    new_engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
        echo=False,
    )
    new_session_local = sessionmaker(
        bind=new_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    db_module.engine = new_engine
    db_module.SessionLocal = new_session_local

    # 把 Base.metadata 的所有表建出来
    from app.db.database import Base, init_db

    Base.metadata.drop_all(bind=new_engine)
    init_db()

    yield {
        "url": db_url,
        "path": db_path,
        "engine": new_engine,
        "session_local": new_session_local,
        "db_module": db_module,
    }

    # teardown
    try:
        Base.metadata.drop_all(bind=new_engine)
    except Exception:
        pass
    db_module.engine = original_engine
    db_module.SessionLocal = original_session_local
    cfg.settings.database_url = original_url
    if db_path.exists():
        try:
            db_path.unlink()
        except Exception:
            pass


@pytest.fixture()
def mock_ctx(sqlite_db, monkeypatch):
    """初始化 mock infra 并 monkey-patch 到 app.* 全局。

    Returns:
        scripts.helpers.mock_infra.LoadTestContext 实例

    关键：mock_infra._install_monkey_patches 会把 WorkflowOrchestrator 的
    create_task / _transition_task / _finalize_task 整体替换成走 MockDB
    的实现，所以即便 sqlite_db 是空的也完全不影响测试逻辑。
    """
    from scripts.helpers import mock_infra

    # 确保所有相关模块已 import（mock_infra 内部依赖这些模块属性）
    import app.services.idempotency  # noqa
    import app.services.retry  # noqa
    import app.services.queue  # noqa
    import app.db.database  # noqa
    import app.services.orchestrator  # noqa
    import app.services.llm_client  # noqa
    import app.agents.base  # noqa
    import app.services.tracing  # noqa
    import app.agents  # noqa

    ctx = mock_infra.init_mock_infra(seed=42)

    yield ctx

    # 重置 mock_infra 内部全局 ctx，避免污染下一个测试
    mock_infra._GLOBAL_CTX = None


@pytest.fixture()
def reset_llm_singleton():
    """某些测试会直接构造 LLMClient，需要在测试间重置 singleton。"""
    from app.services import llm_client as lc

    original = lc._client
    lc._client = None
    yield
    lc._client = original


@pytest.fixture()
def reset_orchestrator_singleton():
    """orchestrator 也是单例；mock_infra 会重置它，但部分测试需要显式重置。"""
    from app.services import orchestrator as oc

    original = oc._orch
    oc._orch = None
    yield
    oc._orch = original