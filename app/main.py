"""FastAPI 主入口"""
from contextlib import asynccontextmanager
import asyncio
import os
import time
import uuid
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.sql import text

from app.core.config import settings
from app.core.logging import get_logger
from app.db.database import init_db, engine
from app.api import asset_router, task_router, dead_letter_router, dashboard_router, trace_router

# 显式触发 models 注册，避免被 Python 优化掉
from app import models  # noqa

logger = get_logger()
DASHBOARD_ROOT = Path(__file__).resolve().parent / "dashboard" / "static"
WEB_DIST_ROOT = Path(__file__).resolve().parent / "web" / "dist"
UPLOAD_ROOT = Path(os.getenv("ADAGENTFLOW_UPLOAD_DIR", "var/uploads")).resolve()
GENERATED_ROOT = Path(os.getenv("ADAGENTFLOW_GENERATED_DIR", "var/generated")).resolve()


# @asynccontextmanager把这个 async def 函数包装成一个异步上下文管理器，FastAPI 会把 yield 之前的代码当作“启动阶段”，yield 之后的代码当作“关闭阶段”
# lifespan 不是普通函数，而是给 FastAPI/ASGI 框架用的生命周期上下文
@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 启动 / 关闭钩子"""
    logger.info("AdAgentFlow API 启动中 ...")
    if settings.database_auto_create:
        init_db()
    yield
    logger.info("AdAgentFlow API 关闭")


app = FastAPI(
    title="AdAgentFlow",
    description="面向电商短视频广告生成的多 Agent 长任务可靠性框架",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", "")[:128] or uuid.uuid4().hex
    started = time.perf_counter()
    with logger.contextualize(message_id=request_id):
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(f"HTTP {request.method} {request.url.path} 未处理异常")
            raise
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            f"HTTP {request.method} {request.url.path} status={response.status_code} "
            f"duration_ms={duration_ms}"
        )
    response.headers["X-Request-ID"] = request_id
    return response

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(task_router, prefix="/api/v1/tasks", tags=["tasks"])
app.include_router(dead_letter_router, prefix="/api/v1/dead-letters", tags=["dead-letters"])
app.include_router(dashboard_router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(trace_router, prefix="/api/v1/traces", tags=["traces"])
app.include_router(asset_router, prefix="/api/v1/assets", tags=["assets"])

# Dashboard 静态文件（旧 Dashboard 目录可能未安装）
if DASHBOARD_ROOT.is_dir():
    app.mount("/dashboard", StaticFiles(directory=DASHBOARD_ROOT), name="dashboard")

# 业务用户 SPA
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
GENERATED_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_ROOT), name="uploads")
app.mount("/generated", StaticFiles(directory=GENERATED_ROOT), name="generated")
app.mount("/web", StaticFiles(directory=WEB_DIST_ROOT, html=True), name="web")


@app.get("/")
async def root():
    dashboard_index = DASHBOARD_ROOT / "index.html"
    if dashboard_index.is_file():
        return FileResponse(dashboard_index)
    return RedirectResponse("/web/")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon_ico():
    return FileResponse("app/web/favicon.svg", media_type="image/svg+xml")


@app.get("/favicon.svg", include_in_schema=False)
async def favicon_svg():
    return FileResponse("app/web/favicon.svg", media_type="image/svg+xml")


@app.get("/live")
async def live():
    """仅表示 API 进程仍可响应。"""
    return {"status": "alive", "service": "AdAgentFlow", "version": "1.0.0"}


@app.get("/ready")
async def ready():
    """真实检查 PostgreSQL、Redis 与 RabbitMQ；失败时返回 503。"""
    checks = {}

    def check_database() -> None:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    try:
        await asyncio.to_thread(check_database)
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"fail:{type(exc).__name__}"

    try:
        from app.services.idempotency import get_redis

        redis = await get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"fail:{type(exc).__name__}"

    try:
        from app.services.queue import get_queue_client

        await get_queue_client().connect()
        checks["rabbitmq"] = "ok"
    except Exception as exc:
        checks["rabbitmq"] = f"fail:{type(exc).__name__}"

    healthy = all(value == "ok" for value in checks.values())
    payload = {"status": "ready" if healthy else "not_ready", "checks": checks}
    return JSONResponse(payload, status_code=200 if healthy else 503)


@app.get("/health")
async def health():
    """兼容旧探针，语义等同 readiness。"""
    return await ready()


@app.get("/metrics", include_in_schema=False)
def metrics():
    """Prometheus scrape endpoint。"""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
