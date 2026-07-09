"""统一日志 - loguru 包装，所有模块共用"""
import sys
from loguru import logger
from app.core.config import settings

# 移除默认 sink，重新配置
logger.remove()
logger.add(
    sys.stdout,
    level=settings.log_level,
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}:{function}:{line}</cyan> | "
    "<level>{message}</level>",
    colorize=True,
)
logger.add(
    "logs/adagentflow_{time:YYYY-MM-DD}.log",
    rotation="100 MB",
    retention="30 days",
    level=settings.log_level,
    enqueue=True,  # 异步写日志
)


def get_logger():
    return logger
