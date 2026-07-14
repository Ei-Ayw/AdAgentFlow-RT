"""Redis 幂等键 + 数据库兜底

写入 Key: idempotent:{task_id}:{step_id}
value: 节点状态 + 时间戳
TTL: 24h
"""
import json
import time
import uuid
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
    """节点执行锁；业务完成状态以数据库 TaskStep 为准。"""
    return f"execution_lock:{task_id}:{step_id}"


def dedup_message_key(message_id: str) -> str:
    return f"dedup:msg:{message_id}"


async def acquire_idempotent(
    task_id: str, step_id: str, *, ttl: Optional[int] = None
) -> Optional[str]:
    """获取带 owner 的执行租约，成功时返回 owner token。

    该锁只防止同一节点并发执行，不承担“永不重跑”的完成去重语义。
    Worker 正常结束时安全释放；异常退出时由短 TTL 自动恢复。
    """
    r = await get_redis()
    key = idempotent_key(task_id, step_id)
    ttl = ttl or settings.redis_execution_lock_ttl
    owner = uuid.uuid4().hex
    marker = json.dumps({"ts": int(time.time()), "step_id": step_id, "owner": owner})
    res = await r.set(name=key, value=marker, nx=True, ex=ttl)
    return owner if res else None


async def release_idempotent(
    task_id: str, step_id: str, owner: Optional[str] = None
) -> bool:
    """仅由锁 owner 释放执行锁；owner=None 仅用于人工恢复清理。"""
    r = await get_redis()
    key = idempotent_key(task_id, step_id)
    if owner is None:
        return bool(await r.delete(key))
    script = """
    local value = redis.call('get', KEYS[1])
    if not value then return 0 end
    local decoded = cjson.decode(value)
    if decoded['owner'] == ARGV[1] then
        return redis.call('del', KEYS[1])
    end
    return 0
    """
    return bool(await r.eval(script, 1, key, owner))


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
    keys = await r.keys("execution_lock:*")
    return len(keys)
