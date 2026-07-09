"""Redis 幂等键 + 数据库兜底

写入 Key: idempotent:{task_id}:{step_id}
value: 节点状态 + 时间戳
TTL: 24h
"""
import json
import time
from typing import Optional
import redis.asyncio as redis_async

from app.core.config import settings
from app.core.logging import get_logger
from app.db.database import session_scope
from app.models.metric import MessageDedup

logger = get_logger()
_pool: Optional[redis_async.Redis] = None


async def get_redis() -> redis_async.Redis:
    global _pool
    if _pool is None:
        _pool = redis_async.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=50,
        )
    return _pool


def idempotent_key(task_id: str, step_id: str) -> str:
    """统一幂等键生成规则"""
    return f"idempotent:{task_id}:{step_id}"


def dedup_message_key(message_id: str) -> str:
    return f"dedup:msg:{message_id}"


async def acquire_idempotent(
    task_id: str, step_id: str, *, ttl: Optional[int] = None
) -> bool:
    """获取幂等锁 - 返回 True 表示本次是该 step 的首次执行

    使用 SETNX (SET ... NX)，底层逻辑：
    1. 如果 key 已经存在，返回 False (已被占)；
    2. 如果 key 不存在，set 并返回 True。
    """
    r = await get_redis()
    key = idempotent_key(task_id, step_id)
    ttl = ttl or settings.redis_idempotent_ttl
    marker = json.dumps({"ts": int(time.time()), "step_id": step_id})
    res = await r.set(name=key, value=marker, nx=True, ex=ttl)
    return bool(res)


async def release_idempotent(task_id: str, step_id: str) -> None:
    """主动释放幂等键 - 用于失败重试或回滚场景"""
    r = await get_redis()
    await r.delete(idempotent_key(task_id, step_id))


async def is_idempotent_held(task_id: str, step_id: str) -> bool:
    """查询幂等键是否被持有"""
    r = await get_redis()
    return await r.exists(idempotent_key(task_id, step_id)) > 0


async def mark_message_seen(message_id: str) -> bool:
    """消息级去重 - 用于 RabbitMQ 重复消费拦截

    Returns:
        True  -> 首次见到，可以处理
        False -> 已见过，跳过
    """
    r = await get_redis()
    key = dedup_message_key(message_id)
    res = await r.set(name=key, value="1", nx=True, ex=3600)
    if not res:
        # DB 兜底记录
        with session_scope() as db:
            try:
                m = MessageDedup(message_id=message_id)
                db.add(m)
                db.commit()
                return True
            except Exception:
                # 已存在
                return False
    return True


async def get_idempotent_count() -> int:
    """统计当前被持有的幂等键数量 - Dashboard 重复消费拦截指标"""
    r = await get_redis()
    keys = await r.keys("idempotent:*")
    return len(keys)
