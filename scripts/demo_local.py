"""AdAgentFlow 本地 Demo - 不依赖 docker，直接在 Python 里跑通完整链路

用法：
    python scripts/demo_local.py

跑通后会打印：
- 每个 Agent 的输入输出
- JSON 校验过程
- 自动修复过程
- 端到端耗时统计
"""
import asyncio
import json
import time
import sys
import os
from pathlib import Path
from typing import Any, Dict

# 项目根路径加进 sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 强制使用 mock 模式，且 DB 用 SQLite
os.environ["USE_MOCK_LLM"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///./demo.db"

# 把 SQLAlchemy URL 改成 SQLite 前缀
from sqlalchemy.engine.url import make_url


# ============================================================
# 重写 DB 引擎为 SQLite for Demo
# ============================================================
def _patch_db_for_sqlite():
    """Demo 模式改用 SQLite"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db import database as db_module

    db_module.engine = create_engine(
        "sqlite:///./demo.db",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    db_module.SessionLocal = sessionmaker(
        bind=db_module.engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


async def demo():
    _patch_db_for_sqlite()

    print("=" * 80)
    print("🚀 AdAgentFlow 本地 Demo")
    print("=" * 80)

    # 初始化 DB
    from app.db.database import init_db

    # 删除已有 db
    try:
        os.remove("demo.db")
    except FileNotFoundError:
        pass
    init_db()
    print("✅ SQLite 表已创建")

    # ---- 准备商品信息 ----
    product = {
        "product_name": "Portable Neck Fan",
        "target_user": "commuters and outdoor workers",
        "selling_points": [
            "hands-free cooling",
            "long battery life",
            "lightweight design",
        ],
        "platform": "TikTok",
        "style": "dramatic before-after ad",
        "duration": 15,
    }
    print(f"\n📦 商品信息:\n{json.dumps(product, ensure_ascii=False, indent=2)}")

    # ---- 直接调用 6 个 Agent 链路（不通过队列）----
    from app.agents import (
        ProductAnalysisAgent,
        ScriptGenerationAgent,
        StoryboardPlanningAgent,
        MaterialSuggestionAgent,
        QualityEvaluationAgent,
    )

    history: Dict[str, Any] = {}
    overall_start = time.time()

    # Step 1: 商品理解
    print("\n" + "=" * 60)
    print("Step 1: 商品理解 Agent")
    print("=" * 60)
    t0 = time.time()
    agent = ProductAnalysisAgent()
    result = await agent.run({"product": product, "history": history})
    print(f"⏱️  耗时: {(time.time() - t0) * 1000:.0f}ms")
    print(f"✅ success: {result.success}")
    if not result.success:
        print(f"❌ failure_reason: {result.failure_reason}")
        print(f"❌ error_message: {result.error_message}")
        return
    history["product_analysis"] = result.output
    print(f"📤 输出:\n{json.dumps(result.output, ensure_ascii=False, indent=2)[:600]}...")

    # Step 2: 脚本生成
    print("\n" + "=" * 60)
    print("Step 2: 脚本生成 Agent")
    print("=" * 60)
    t0 = time.time()
    agent = ScriptGenerationAgent()
    result = await agent.run({"product": product, "history": history})
    print(f"⏱️  耗时: {(time.time() - t0) * 1000:.0f}ms")
    history["script_generation"] = result.output
    print(f"📤 输出:\n{json.dumps(result.output, ensure_ascii=False, indent=2)[:600]}...")

    # Step 3: 分镜规划
    print("\n" + "=" * 60)
    print("Step 3: 分镜规划 Agent")
    print("=" * 60)
    t0 = time.time()
    agent = StoryboardPlanningAgent()
    result = await agent.run({"product": product, "history": history})
    print(f"⏱️  耗时: {(time.time() - t0) * 1000:.0f}ms")
    history["storyboard_planning"] = result.output
    print(f"📤 输出:\n{json.dumps(result.output, ensure_ascii=False, indent=2)[:500]}...")

    # Step 4: 素材建议
    print("\n" + "=" * 60)
    print("Step 4: 素材建议 Agent")
    print("=" * 60)
    t0 = time.time()
    agent = MaterialSuggestionAgent()
    result = await agent.run({"product": product, "history": history})
    print(f"⏱️  耗时: {(time.time() - t0) * 1000:.0f}ms")
    history["material_suggestion"] = result.output
    print(f"📤 输出: {len(result.output.get('materials', []))} 个素材建议")

    # Step 5: 质量评估
    print("\n" + "=" * 60)
    print("Step 5: 质量评估 Agent (LLM-as-Judge)")
    print("=" * 60)
    t0 = time.time()
    agent = QualityEvaluationAgent()
    result = await agent.run({"product": product, "history": history})
    print(f"⏱️  耗时: {(time.time() - t0) * 1000:.0f}ms")
    history["quality_evaluation"] = result.output
    print(f"📤 评分: {result.output.get('score')}, passed: {result.output.get('passed')}")
    print(f"📤 risk_level: {result.output.get('risk_level')}")
    print(f"📤 issues: {len(result.output.get('issues', []))}")

    # ---- 总结 ----
    total_time = (time.time() - overall_start) * 1000
    print("\n" + "=" * 80)
    print(f"🎉 端到端耗时: {total_time:.0f}ms ({total_time / 1000:.2f}s)")
    print(f"📊 总节点数: {len(history)}")
    print(f"📊 总 LLM 调用: {len(history)}")
    print("=" * 80)

    # 输出最终结果
    print("\n📋 最终产出:")
    print(json.dumps({
        "script": history.get("script_generation", {}),
        "storyboard_count": len(history.get("storyboard_planning", {}).get("storyboard", [])),
        "material_count": len(history.get("material_suggestion", {}).get("materials", [])),
        "quality_score": history.get("quality_evaluation", {}).get("score"),
        "passed": history.get("quality_evaluation", {}).get("passed"),
    }, ensure_ascii=False, indent=2)[:1500])


if __name__ == "__main__":
    asyncio.run(demo())
