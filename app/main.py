"""FastAPI 主入口"""
from contextlib import asynccontextmanager
import asyncio
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.sql import text

from app.core.config import settings
from app.core.logging import get_logger
from app.db.database import init_db, engine
from app.api import task_router, dead_letter_router, dashboard_router, trace_router

# 显式触发 models 注册，避免被 Python 优化掉
from app import models  # noqa

logger = get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 启动 / 关闭钩子"""
    logger.info("AdAgentFlow API 启动中 ...")
    init_db()
    yield
    logger.info("AdAgentFlow API 关闭")


app = FastAPI(
    title="AdAgentFlow",
    description="面向电商短视频广告生成的多 Agent 长任务可靠性框架",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(task_router, prefix="/api/v1/tasks", tags=["tasks"])
app.include_router(dead_letter_router, prefix="/api/v1/dead-letters", tags=["dead-letters"])
app.include_router(dashboard_router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(trace_router, prefix="/api/v1/traces", tags=["traces"])

# Dashboard 静态文件
app.mount("/dashboard", StaticFiles(directory="app/dashboard/static"), name="dashboard")


@app.get("/")
async def root():
    return FileResponse("app/dashboard/static/index.html")


@app.get("/health")
async def health():
    """健康检查"""
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "healthy", "service": "AdAgentFlow", "version": "1.0.0"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
