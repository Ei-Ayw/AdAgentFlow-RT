"""AdAgentFlow 压测 + 故障模拟入口脚本

可独立运行的 CLI 压测工具，覆盖 6 大场景：

    # 1. 正常并发压测
    python scripts/load_test.py --scenario concurrent --concurrency 200

    # 2. JSON 异常模拟
    python scripts/load_test.py --scenario bad_json --concurrency 50

    # 3. Worker 崩溃模拟
    python scripts/load_test.py --scenario worker_crash --concurrency 100

    # 4. 重复消息投递
    python scripts/load_test.py --scenario duplicate --concurrency 100

    # 5. 模型超时
    python scripts/load_test.py --scenario timeout --concurrency 100

    # 6. 评估不通过 → 修复 agent
    python scripts/load_test.py --scenario judge_fail --concurrency 50

    # 跑全部
    python scripts/load_test.py --scenario all

注意：
- 默认使用 mock 模式，不依赖 docker / RabbitMQ / Redis / PG。
- 输出 reports/metrics.json + reports/load_test_report.md。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

# 把项目根加入 path，方便 import app.* 与本地 modules
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 项目里既存的 import bug：app.agents.base 从 app.services.json_validator 导入
# pydantic_to_json_schema，但这个函数实际定义在 app.schemas.agent_schemas。
# 我们提前 monkey-patch 修一下，让压测代码能正常 import。
import app.services.json_validator as _jv
from app.schemas.agent_schemas import pydantic_to_json_schema as _p2js  # noqa: E402

if not hasattr(_jv, "pydantic_to_json_schema"):
    _jv.pydantic_to_json_schema = _p2js

# === 关键：先把 app.* 全部 import 进来，再 monkey-patch 它们的属性。
# 因为 orchestrator 用的是 `from app.services.idempotency import acquire_idempotent`，
# 我们必须在 import orchestrator 之后，同时 patch 它内部的本地引用。
import app.services.idempotency as _idem_mod
import app.services.retry as _retry_mod
import app.services.queue as _queue_mod
import app.db.database as _db_mod
import app.services.orchestrator as _orch_mod
import app.services.llm_client as _llm_mod
import app.agents.base as _agent_base_mod

from scripts.helpers.metrics_collector import MetricsCollector  # noqa: E402
from scripts.helpers.mock_infra import init_mock_infra, _install_monkey_patches  # noqa: E402
from scripts.failure_scenarios import (
    run_scenario_concurrent,
    run_scenario_bad_json,
    run_scenario_worker_crash,
    run_scenario_duplicate,
    run_scenario_timeout,
    run_scenario_judge_fail,
)
from scripts.report_generator import generate_reports


SCENARIO_MAP = {
    "concurrent": ("并发压测", run_scenario_concurrent),
    "bad_json": ("JSON 异常模拟", run_scenario_bad_json),
    "worker_crash": ("Worker 崩溃模拟", run_scenario_worker_crash),
    "duplicate": ("重复消息投递", run_scenario_duplicate),
    "timeout": ("模型超时模拟", run_scenario_timeout),
    "judge_fail": ("评估不通过 → 修复", run_scenario_judge_fail),
}


async def run_one(scenario: str, args, collector: MetricsCollector) -> None:
    """跑单个场景"""
    name, runner = SCENARIO_MAP[scenario]
    print(f"\n{'=' * 70}\n>>> 场景: {name} ({scenario})\n{'=' * 70}")
    await runner(args, collector)


async def main() -> None:
    parser = argparse.ArgumentParser(description="AdAgentFlow 压测 + 故障模拟")
    parser.add_argument(
        "--scenario",
        default="concurrent",
        choices=list(SCENARIO_MAP.keys()) + ["all"],
        help="压测场景 (默认 concurrent)",
    )
    parser.add_argument("--concurrency", type=int, default=50, help="并发任务数")
    parser.add_argument("--duration", type=int, default=30, help="持续时间(秒)，部分场景使用")
    parser.add_argument(
        "--bad-json-rate",
        type=float,
        default=0.7,
        help="场景2中坏JSON注入比例 (0-1)",
    )
    parser.add_argument(
        "--timeout-rate",
        type=float,
        default=0.3,
        help="场景5中模型超时注入比例 (0-1)",
    )
    parser.add_argument(
        "--crash-at",
        type=int,
        default=50,
        help="场景3中在第N个任务时模拟 worker crash",
    )
    parser.add_argument(
        "--replication",
        type=int,
        default=2,
        help="场景4中每条消息的重复投递次数",
    )
    parser.add_argument(
        "--judge-pass-rate",
        type=float,
        default=0.0,
        help="场景6中评估通过率 (0-1, 默认全部失败)",
    )
    parser.add_argument(
        "--reports-dir",
        default=str(ROOT / "reports"),
        help="报告输出目录",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="随机种子 (保证可复现)",
    )
    args = parser.parse_args()

    # 初始化 mock 基础设施
    init_mock_infra(seed=args.seed)

    collector = MetricsCollector(scenario=args.scenario)

    started = time.time()
    if args.scenario == "all":
        for key in SCENARIO_MAP.keys():
            # 重置 mock 状态，避免上一个场景的幂等键影响
            init_mock_infra(seed=args.seed)
            await run_one(key, args, collector)
    else:
        await run_one(args.scenario, args, collector)
    elapsed = time.time() - started

    print(f"\n全部场景完成，总耗时 {elapsed:.2f}s")

    # 生成报告
    md_path, json_path = generate_reports(collector.snapshot_all(), args.reports_dir)
    print(f"\n报告已生成:\n  - Markdown: {md_path}\n  - JSON: {json_path}")


if __name__ == "__main__":
    asyncio.run(main())