"""统一结构化日志；通过 contextualize 关联任务、节点和消息。"""
import sys
import os
from loguru import logger
from app.core.config import settings

# 移除默认 sink，重新配置
logger.remove()
json_logs = settings.log_format.lower() == "json"
logger.configure(
    extra={
        "service": settings.service_name,
        "instance": os.getenv("HOSTNAME", "local"),
        "task_id": None,
        "step_id": None,
        "message_id": None,
        "trace_id": None,
        "execution_id": None,
    }
)
logger.add(
    sys.stdout,
    level=settings.log_level,
    serialize=json_logs,
    format=(
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
        "{name}:{function}:{line} | {message} | {extra}"
    ),
    colorize=not json_logs,
    backtrace=False,
    diagnose=False,
)
logger.add(
    "logs/adagentflow_{time:YYYY-MM-DD}.log",
    rotation="100 MB",
    retention="30 days",
    level=settings.log_level,
    enqueue=True,  # 异步写日志
    serialize=json_logs,
    backtrace=False,
    diagnose=False,
)


def get_logger():
    return logger
