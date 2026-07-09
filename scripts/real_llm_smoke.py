"""Real-LLM 端到端冒烟 - 10 个商品 in-process 跑通

用法:
  # 1) export 真实 LLM 凭证
  export ANTHROPIC_AUTH_TOKEN="..."
  export ANTHROPIC_BASE_URL="https://api.minimaxi.com/anthropic"
  export ANTHROPIC_DEFAULT_HAIKU_MODEL="MiniMax-M3"
  export USE_MOCK_LLM=false
  export DATABASE_URL="sqlite:///./real_llm_run.db"

  # 2) python scripts/real_llm_smoke.py

设计要点：
- 不依赖 RabbitMQ / Redis（用 in-process mock / fallback）
- 把真实 LLM 错误透传，不静默回退 mock
- 10 个不同商品的端到端流程
- 跑完输出总 token、成功率、平均耗时
- 数据落 SQLite (real_llm_run.db)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ================================================================
# 环境设置 - 在 import app.* 之前完成
# ================================================================
# 必须有真实 token，否则直接报错
if not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
    print("ERROR: ANTHROPIC_AUTH_TOKEN 未设置", file=sys.stderr)
    sys.exit(2)
os.environ.setdefault("ANTHROPIC_BASE_URL", "https://api.minimaxi.com/anthropic")
os.environ.setdefault("ANTHROPIC_DEFAULT_HAIKU_MODEL", "MiniMax-M3")
os.environ.setdefault("USE_MOCK_LLM", "false")
os.environ.setdefault("DATABASE_URL", "sqlite:///./real_llm_run.db")
# 让 Redis / RabbitMQ 故意连不上, orchestrator 应回退 / 走 in-process
os.environ.setdefault("REDIS_URL", "redis://localhost:9999/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@127.0.0.1:1/")


# ================================================================
# 1) DB 用 SQLite
# ================================================================
def _init_sqlite_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db import database as db_module

    db_url = os.environ["DATABASE_URL"]
    # 删掉旧 DB
    if db_url.startswith("sqlite:///"):
        db_file = db_url.replace("sqlite:///", "")
        if db_file.startswith("./"):
            db_file = db_file[2:]
        try:
            os.remove(db_file)
        except FileNotFoundError:
            pass

    db_module.engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
        echo=False,
        future=True,
    )
    db_module.SessionLocal = sessionmaker(
        bind=db_module.engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    return db_module


# ================================================================
# 2) In-process 队列：让 orchestrator.execute_step 同步跑
# ================================================================
class InProcessQueue:
    """内存队列，publish 时直接 push 进 messages，外部 loop 异步消费"""

    def __init__(self):
        self.messages: List[Dict[str, Any]] = []

    async def connect(self):
        pass

    async def close(self):
        pass

    async def publish(self, routing_key, body):
        self.messages.append(body)

    async def publish_step(self, task_id, step_id, payload):
        self.messages.append({
            "task_id": task_id,
            "step_id": step_id,
            "payload": payload,
        })

    async def publish_dead_letter(self, task_id, step_id, payload):
        self.messages.append({
            "type": "dead_letter",
            "task_id": task_id,
            "step_id": step_id,
            "payload": payload,
        })


# ================================================================
# 3) In-process 幂等：内存 set
# ================================================================
_idem_store: set = set()


async def _acquire_idempotent(task_id: str, step_id: str, *, ttl: Optional[int] = None) -> bool:
    key = f"{task_id}:{step_id}"
    if key in _idem_store:
        return False
    _idem_store.add(key)
    return True


# ================================================================
# 4) 10 个真实商品样本
# ================================================================
PRODUCTS: List[Dict[str, Any]] = [
    {
        "product_name": "Portable Neck Fan Pro",
        "target_user": "commuters and delivery riders",
        "selling_points": ["hands-free cooling", "6h battery", "180g lightweight"],
        "platform": "TikTok",
        "style": "before-after dramatic",
        "duration": 15,
    },
    {
        "product_name": "Smart Posture Corrector",
        "target_user": "office workers and students",
        "selling_points": ["vibration reminder", "invisible under clothes", "app stats"],
        "platform": "Instagram Reels",
        "style": "lifestyle testimonial",
        "duration": 20,
    },
    {
        "product_name": "Mini Espresso Machine",
        "target_user": "apartment dwellers and travelers",
        "selling_points": ["20s brewing", "USB-C charge", "no pods needed"],
        "platform": "TikTok",
        "style": "POV satisfying",
        "duration": 15,
    },
    {
        "product_name": "Pet Hair Removal Roller",
        "target_user": "cat and dog owners",
        "selling_points": ["reusable", "no refill needed", "self-cleaning base"],
        "platform": "Douyin",
        "style": "problem-solution demo",
        "duration": 15,
    },
    {
        "product_name": "Blue Light Blocking Glasses",
        "target_user": "remote workers and gamers",
        "selling_points": ["amber lens", "anti-fatigue", "lightweight TR90"],
        "platform": "YouTube Shorts",
        "style": "tech review",
        "duration": 30,
    },
    {
        "product_name": "Collapsible Silicone Water Bottle",
        "target_user": "hikers and gym goers",
        "selling_points": ["folds to 5cm", "BPA free", "holds 600ml"],
        "platform": "TikTok",
        "style": "outdoor adventure",
        "duration": 15,
    },
    {
        "product_name": "Magnetic Phone Car Mount",
        "target_user": "rideshare drivers and daily commuters",
        "selling_points": ["strong neodymium magnets", "one-hand attach", "rotates 360"],
        "platform": "Instagram Reels",
        "style": "fast-cut utility",
        "duration": 15,
    },
    {
        "product_name": "Smart Plant Watering Bulb",
        "target_user": "busy urbanites with houseplants",
        "selling_points": ["self-watering 2 weeks", "cute design", "transparent reservoir"],
        "platform": "Pinterest Video",
        "style": "cozy lifestyle",
        "duration": 20,
    },
    {
        "product_name": "Cordless Hair Straightener",
        "target_user": "frequent travelers and busy professionals",
        "selling_points": ["30min cordless use", "USB-C fast charge", "ceramic tourmaline"],
        "platform": "TikTok",
        "style": "GRWM transformation",
        "duration": 30,
    },
    {
        "product_name": "Reusable Silicone Food Bags",
        "target_user": "eco-conscious parents and meal preppers",
        "selling_points": ["replaces 300 ziplocks/yr", "dishwasher safe", "leakproof seal"],
        "platform": "YouTube Shorts",
        "style": "zero-waste explainer",
        "duration": 25,
    },
]


# ================================================================
# 5) 跑一个端到端任务
# ================================================================
async def run_one_task(
    orch,
    queue: InProcessQueue,
    product: Dict[str, Any],
) -> Dict[str, Any]:
    """跑一条任务, 直到队列空 / 死信 / 最多 30 步"""
    started = time.time()
    task_id = await orch.create_task(product)
    trace_id = ""
    executed = []
    error_msgs: List[str] = []
    iters = 0
    max_iters = 30

    while queue.messages and iters < max_iters:
        iters += 1
        msg = queue.messages.pop(0)
        if msg.get("type") == "dead_letter":
            error_msgs.append(f"dead_letter: {msg.get('step_id')}")
            break
        tid = msg["task_id"]
        sid = msg["step_id"]
        payload = msg["payload"]
        trace_id = payload.get("trace_id", trace_id)
        try:
            await orch.execute_step(tid, sid, payload)
            executed.append(sid)
        except Exception as e:
            tb = traceback.format_exc()
            error_msgs.append(f"execute_step({sid}) exception: {e}\n{tb}")
            break

    elapsed = (time.time() - started) * 1000
    return {
        "task_id": task_id,
        "trace_id": trace_id,
        "product_name": product["product_name"],
        "executed_steps": executed,
        "step_count": len(executed),
        "elapsed_ms": int(elapsed),
        "error_msgs": error_msgs,
    }


# ================================================================
# 6) 主流程
# ================================================================
async def main():
    print("=" * 80)
    print("Real-LLM End-to-End Smoke (10 products)")
    print("=" * 80)
    print(f"DB: {os.environ['DATABASE_URL']}")
    print(f"LLM base_url: {os.environ.get('ANTHROPIC_BASE_URL')}")
    print(f"LLM model: {os.environ.get('ANTHROPIC_DEFAULT_HAIKU_MODEL')}")
    print(f"USE_MOCK_LLM: {os.environ.get('USE_MOCK_LLM')}")
    print()

    # 1. SQLite + create tables
    db_module = _init_sqlite_db()
    from app.db.database import init_db
    init_db()
    print("[1/5] SQLite tables created")

    # 2. Inject in-process queue + idempotency
    from app.services import orchestrator as _orch
    from app.services import idempotency as _idem

    queue = InProcessQueue()
    _orch.get_queue_client = lambda: queue
    _idem.acquire_idempotent = _acquire_idempotent
    _orch.acquire_idempotent = _acquire_idempotent
    # 清掉单例, 重新拿
    try:
        _orch._orch = None
    except Exception:
        pass

    from app.services.orchestrator import get_orchestrator
    orch = get_orchestrator()
    orch.queue = queue
    print("[2/5] In-process queue + idempotency installed")

    # 3. 验证 LLM client 是真实模式
    from app.services.llm_client import get_llm_client
    llm = get_llm_client()
    print(f"[3/5] LLM client: model={llm.model} use_mock={llm.use_mock} base_url={llm.base_url}")
    if llm.use_mock:
        print("WARNING: LLM client 仍在 mock 模式 - 检查 USE_MOCK_LLM / token 配置")
        sys.exit(3)

    # 4. 跑 10 个任务
    results: List[Dict[str, Any]] = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_latency = 0
    success_count = 0
    print(f"[4/5] Running {len(PRODUCTS)} tasks...")
    for i, product in enumerate(PRODUCTS, 1):
        _idem_store.clear()
        try:
            r = await run_one_task(orch, queue, product)
        except Exception as e:
            tb = traceback.format_exc()
            r = {
                "task_id": f"<spawn-failed-{i}>",
                "product_name": product["product_name"],
                "executed_steps": [],
                "step_count": 0,
                "elapsed_ms": 0,
                "error_msgs": [f"{type(e).__name__}: {e}\n{tb}"],
            }
        results.append(r)
        status = "OK" if not r["error_msgs"] else "FAIL"
        print(f"  [{i:2d}/10] {status}  {r['product_name']:36s}  steps={r['step_count']}  {r['elapsed_ms']}ms"
              f"  errs={len(r['error_msgs'])}")

    # 5. 汇总 - 查 task_traces / agent_metrics
    from sqlalchemy import text
    from app.db.database import engine
    print("[5/5] Aggregating from DB ...")

    trace_rows = []
    metric_rows = []
    evaluation_rows = []
    try:
        with engine.connect() as c:
            trace_rows = list(c.execute(text(
                "SELECT step_id, event_type, model_name, prompt_version, token_cost, latency_ms "
                "FROM task_traces WHERE event_type IN ('step.start','step.success','step.fail') "
                "ORDER BY id"
            )))
            metric_rows = list(c.execute(text(
                "SELECT step_name, total_executions, success_executions, failed_executions, "
                "total_token_cost, total_latency_ms FROM agent_metrics ORDER BY step_name"
            )))
            evaluation_rows = list(c.execute(text(
                "SELECT step_id, score, passed, risk_level FROM evaluation_results ORDER BY id"
            )))
    except Exception as e:
        print(f"DB query failed: {e}")

    # token 统计
    total_in = 0
    total_out = 0
    for r in trace_rows:
        # token_cost = in+out; 暂用整型 (没有 in/out 拆分存储, 但 client 已记录)
        total_input_tokens += 0  # 不拆分, 只在 metric 里看
        total_output_tokens += 0
    # 从 metric 取真实 token 总量
    total_token_cost_metric = 0
    total_latency_metric = 0
    for row in metric_rows:
        total_token_cost_metric += int(row[4] or 0)
        total_latency_metric += int(row[5] or 0)

    # 成功率 (用最终 task 状态判断)
    final_task_rows = []
    try:
        with engine.connect() as c:
            final_task_rows = list(c.execute(text(
                "SELECT task_id, status FROM tasks ORDER BY created_at"
            )))
    except Exception:
        pass
    success_statuses = {"success"}
    success_count = sum(1 for r in final_task_rows if r[1] in success_statuses)
    if not final_task_rows:
        # 退化: 看 error_msgs 是否为空
        success_count = sum(1 for r in results if not r["error_msgs"])

    # 计算平均耗时
    elapsed_list = [r["elapsed_ms"] for r in results if r["elapsed_ms"] > 0]
    avg_elapsed = sum(elapsed_list) / len(elapsed_list) if elapsed_list else 0

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Tasks run:        {len(results)}")
    print(f"Success tasks:    {success_count} / {len(results)}")
    print(f"Total tokens:     {total_token_cost_metric}  (from agent_metrics.total_token_cost)")
    print(f"Avg tokens/task:  {total_token_cost_metric / max(len(results), 1):.0f}")
    print(f"Total latency:    {total_latency_metric}ms  (sum across agent_metrics)")
    print(f"Avg task elapsed: {avg_elapsed:.0f}ms")
    print()

    print("--- agent_metrics ---")
    print(f"{'step_name':<24} {'total':>6} {'ok':>6} {'fail':>6} {'token':>10} {'latency':>10}")
    for row in metric_rows:
        print(f"{row[0]:<24} {row[1]:>6} {row[2]:>6} {row[3]:>6} {row[4]:>10} {row[5]:>10}")

    print()
    print("--- evaluation_results ---")
    if evaluation_rows:
        for row in evaluation_rows:
            print(f"  {row[0]:<24} score={row[1]} passed={row[2]} risk={row[3]}")
    else:
        print("  (no rows)")

    print()
    print("--- final task statuses ---")
    for row in final_task_rows:
        print(f"  {row[0][:30]:<32} -> {row[1]}")

    print()
    if any(r["error_msgs"] for r in results):
        print("--- errors encountered ---")
        for r in results:
            if r["error_msgs"]:
                print(f"\n  Task {r['product_name']}:")
                for e in r["error_msgs"][:3]:
                    print(f"    {e[:400]}")

    # 退出码: 全部成功 -> 0, 否则 -> 1
    if success_count == len(results) and not any(r["error_msgs"] for r in results):
        print("\nAll tasks succeeded.")
        return 0
    else:
        print(f"\n{len(results) - success_count} tasks failed.")
        return 1


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
