"""Run production-stress smoke experiments and write JSONL results."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from experiments.harness.benchmark_adapters.agentchange_adapter import AgentChangeBenchmarkAdapter
from experiments.harness.benchmark_adapters.base import MockBenchmarkAdapter
from experiments.harness.benchmark_adapters.tau3_adapter import Tau3BenchmarkAdapter
from experiments.harness.runtime_adapters.adagentflow_rt import AdAgentFlowRTAdapter
from experiments.harness.runtime_adapters.retry_only import RetryOnlyAdapter
from experiments.harness.runtime_adapters.schema_only import SchemaOnlyAdapter
from experiments.harness.runtime_adapters.vanilla_tool_calling import VanillaToolCallingAdapter
from experiments.harness.stressors.duplicate_message import DuplicateMessageStressor
from experiments.harness.stressors.partial_response import PartialResponseStressor
from experiments.harness.stressors.rate_limit import RateLimitStressor
from experiments.harness.stressors.schema_drift import SchemaDriftStressor
from experiments.harness.stressors.stale_context import StaleContextStressor
from experiments.harness.stressors.tool_timeout import ToolTimeoutStressor
from experiments.harness.stressors.worker_crash import WorkerCrashStressor
from experiments.harness.workload.concurrency_runner import run_tasks


BENCHMARKS = {
    "mock": MockBenchmarkAdapter,
    "tau3": Tau3BenchmarkAdapter,
    "agentchange": AgentChangeBenchmarkAdapter,
}

RUNTIMES = {
    "vanilla": VanillaToolCallingAdapter,
    "retry_only": RetryOnlyAdapter,
    "schema_only": SchemaOnlyAdapter,
    "adagentflow_rt": AdAgentFlowRTAdapter,
}

STRESSORS = {
    "tool_timeout": ToolTimeoutStressor,
    "rate_limit": RateLimitStressor,
    "partial_response": PartialResponseStressor,
    "schema_drift": SchemaDriftStressor,
    "stale_context": StaleContextStressor,
    "duplicate_message": DuplicateMessageStressor,
    "worker_crash": WorkerCrashStressor,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", default="mock", choices=sorted(BENCHMARKS))
    parser.add_argument("--domain", default="airline")
    parser.add_argument("--num-tasks", type=int, default=3)
    parser.add_argument("--num-trials", type=int, default=1)
    parser.add_argument("--methods", default="vanilla,retry_only,schema_only,adagentflow_rt")
    parser.add_argument("--stress", default="")
    parser.add_argument("--fault-rate", type=float, default=0.0)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--output", default="experiments/results/smoke/mock_smoke.jsonl")
    args = parser.parse_args()

    config = {
        "domain": args.domain,
        "num_tasks": args.num_tasks,
        "num_trials": args.num_trials,
        "max_concurrency": args.max_concurrency,
    }
    adapter = BENCHMARKS[args.benchmark]()
    tasks = list(adapter.load_tasks(config))
    stressors = build_stressors(args.stress, args.fault_rate)
    methods = [method.strip() for method in args.methods.split(",") if method.strip()]

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        for method in methods:
            runtime = RUNTIMES[method]()
            results = run_tasks(
                tasks=tasks,
                adapter=runtime,
                stressors=stressors,
                runtime_config={"max_retries": 2},
                max_concurrency=args.max_concurrency,
            )
            for result in results:
                fh.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n")


def build_stressors(stress: str, fault_rate: float) -> List[Any]:
    stressors = []
    for idx, name in enumerate(part.strip() for part in stress.split(",") if part.strip()):
        stressors.append(STRESSORS[name](rate=fault_rate, seed=idx + 17))
    return stressors


if __name__ == "__main__":
    main()
