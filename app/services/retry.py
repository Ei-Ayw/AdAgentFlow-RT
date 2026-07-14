"""失败重试服务 - 指数退避 + 死信判定

重试策略：
- 第 1 次：立即
- 第 2 次：5s
- 第 3 次：15s
- 超过：进死信

按 failure_reason 选择修复策略
"""
import asyncio
import json
import time
from typing import Any, Dict, Optional, Tuple

from app.core.config import settings
from app.core.logging import get_logger
from app.core.failure_codes import FailureReason, REPAIR_STRATEGY
from app.db.database import session_scope
from app.models.task import Task
from app.models.step import TaskStep
from app.models.dead_letter import DeadLetter

logger = get_logger()


def compute_retry_delay(retry_count: int) -> int:
    """根据 retry_count 计算下次重试延迟 (秒)"""
    delays = settings.retry_delay_list
    if not delays:
        delays = [0, 5, 15]
    idx = min(retry_count, len(delays) - 1)
    return delays[idx]


def should_retry(retry_count: int, max_retry: int) -> bool:
    return retry_count < max_retry


def choose_repair_strategy(failure_reason: str) -> str:
    """根据 failure_reason 决定修复策略名"""
    try:
        fr = FailureReason(failure_reason)
        return REPAIR_STRATEGY.get(fr, "dead_letter")
    except ValueError:
        return "dead_letter"


async def sleep_retry(retry_count: int) -> None:
    """睡眠对应时长（异步，不阻塞 worker）"""
    delay = compute_retry_delay(retry_count)
    if delay > 0:
        logger.info(f"重试前等待 {delay}s ...")
        await asyncio.sleep(delay)


def mark_task_retrying(task_id: str, failure_reason: str, error_message: str) -> int:
    """把任务标记为 retrying 并累加 retry_count

    Returns:
        新的 retry_count
    """
    with session_scope() as db:
        task = db.query(Task).filter(Task.task_id == task_id).with_for_update().first()
        if not task:
            logger.error(f"任务不存在: {task_id}")
            return 0
        task.retry_count = (task.retry_count or 0) + 1
        task.last_failure_reason = failure_reason
        task.status = "retrying"
        rc = task.retry_count
        return rc


def send_to_dead_letter(
    task_id: str,
    step_id: str,
    failure_reason: str,
    input_payload: dict,
    last_output: Any,
    retry_count: int,
    error_message: str,
) -> None:
    """将任务/节点送入死信"""
    with session_scope() as db:
        dl = DeadLetter(
            task_id=task_id,
            step_id=step_id,
            failure_reason=failure_reason,
            input_payload=input_payload,
            last_output=last_output if isinstance(last_output, (dict, list)) else {"raw": str(last_output)},
            retry_count=retry_count,
            error_message=error_message,
        )
        db.add(dl)
        # 任务状态置为 dead_letter
        task = db.query(Task).filter(Task.task_id == task_id).first()
        if task:
            task.status = "dead_letter"
            task.finished_at = task.finished_at or func_now()
            task.last_failure_reason = failure_reason


def func_now():
    from sqlalchemy.sql import func

    return func.now()
