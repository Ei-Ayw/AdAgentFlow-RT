"""统一 import 子 router"""
from app.api.task_router import router as task_router
from app.api.dead_letter_router import router as dead_letter_router
from app.api.dashboard_router import router as dashboard_router
from app.api.trace_router import router as trace_router
from app.api.asset_router import router as asset_router

__all__ = ["task_router", "dead_letter_router", "dashboard_router", "trace_router", "asset_router"]
