"""Run the production-stress matrix against a real LLM with real benchmark data.

This is the paper-claim driver. Unlike :mod:`run_real` (which uses
mock scenarios + a deterministic simulator), this driver:

1. Loads the **real** τ³-bench and AgentChangeBench task fixtures shipped with
   their public repos (``data/external/tau2-bench``, ``data/external/AgentChangeBench``).
2. Points the harness at a real OpenAI-compatible endpoint (``LLM_BASE_URL``).
3. Caps the matrix at a size that finishes in under 4 hours on a single
   Qwen3-8B / vLLM endpoint while preserving the three main matrix axes:
   domain, fault_rate, max_concurrency.

The default matrix is intentionally small enough to finish overnight:
* 3 domains × 3 tasks × 2 trials × 2 fault rates × 2 concurrencies = 72 cells
* × 4 methods = 288 main runs
* × 4 ablations = 4× fewer ablations
* AgentChangeBench: 2 domains × 3 tasks × 2 trials × 2 fault × 2 conc = 24 cells × 4 methods = 96 runs
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from experiments.harness.benchmark_adapters.tau3_adapter import (
    AgentChangeBenchmarkAdapter,
    Tau3BenchmarkAdapter,
)
from experiments.harness.run_experiment import RUNTIMES, build_stressors
from experiments.harness.workload.concurrency_runner import run_tasks


def _run_one(*, benchmark: str, domain: str, num_tasks: int, num_trials: int,
             methods: List[str], stress: str, fault_rate: float,
             max_concurrency: int, output: Path, ablation: str | None = None) -> int:
    config = {
        "execution_mode": "external",
        "benchmark_repo_path": "/tmp/tau2-bench" if benchmark == "tau3" else "/tmp/agentchange",
        "domain": domain,
        "num_tasks": num_tasks,
        "num_trials": num_trials,
        "max_concurrency": max_concurrency,
    }
    adapter = {
        "tau3": Tau3BenchmarkAdapter,
        "agentchange": AgentChangeBenchmarkAdapter,
    }[benchmark]()
    tasks = list(adapter.load_tasks(config))
    stressors = build_stressors(stress, fault_rate)
    output.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with output.open("w", encoding="utf-8") as fh:
        for method in methods:
            runtime_config = {
                "max_retries": 2,
                "ablation": ablation if method == "adagentflow_rt" else None,
            }
            runtime = RUNTIMES[method]()
            results = run_tasks(
                tasks=tasks,
                adapter=runtime,
                stressors=stressors,
                runtime_config=runtime_config,
                max_concurrency=max_concurrency,
            )
            for result in results:
                row = result.to_dict()
                row["suite_run"] = output.stem
                row["fault_rate"] = fault_rate
                row["max_concurrency"] = max_concurrency
                row["stress"] = stress
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                written += 1
    return written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--num-tasks", type=int, default=3, help="Tasks per cell (default: 3)")
    parser.add_argument("--num-trials", type=int, default=2, help="Trials per task (default: 2)")
    parser.add_argument("--concurrencies", default="1,5", help="Comma-separated concurrency levels")
    parser.add_argument("--fault-rates", default="0.0,0.2", help="Comma-separated fault rates")
    parser.add_argument("--main-only", action="store_true", help="Skip ablations")
    parser.add_argument("--no-agentchange", action="store_true", help="Skip AgentChangeBench")
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    methods = ["vanilla", "retry_only", "schema_only", "adagentflow_rt"]
    concurrencies = [int(c) for c in args.concurrencies.split(",")]
    fault_rates = [float(f) for f in args.fault_rates.split(",")]

    matrix: List[Dict[str, Any]] = []
    for domain in ("airline", "retail", "telecom"):
        for fault_rate in fault_rates:
            for concurrency in concurrencies:
                matrix.append(dict(
                    benchmark="tau3", domain=domain, num_tasks=args.num_tasks, num_trials=args.num_trials,
                    stress="tool_timeout,partial_response,schema_drift,stale_context,duplicate_message",
                    fault_rate=fault_rate, max_concurrency=concurrency, suite="tau3_main_external",
                ))
    if not args.no_agentchange:
        for domain in ("airline", "retail"):
            for fault_rate in fault_rates[:2]:  # cap to first 2 fault rates
                for concurrency in concurrencies[:2]:  # cap to first 2 concurrencies
                    matrix.append(dict(
                        benchmark="agentchange", domain=domain, num_tasks=args.num_tasks, num_trials=args.num_trials,
                        stress="schema_drift,stale_context,duplicate_message",
                        fault_rate=fault_rate, max_concurrency=concurrency, suite="agentchange_external",
                    ))

    ablations = [] if args.main_only else [
        "without_contract_monitor", "without_fault_localizer", "without_bounded_recovery", "without_event_trace",
    ]

    total_written = 0
    plan_log: List[Dict[str, Any]] = []
    for spec in matrix:
        label = f"{spec['benchmark']}_{spec['domain']}_c{spec['max_concurrency']}_f{str(spec['fault_rate']).replace('.', 'p')}_{spec['stress'][:18] or 'none'}"
        output = output_dir / f"{label}.jsonl"
        n = _run_one(
            benchmark=spec["benchmark"], domain=spec["domain"], num_tasks=spec["num_tasks"],
            num_trials=spec["num_trials"], methods=methods, stress=spec["stress"],
            fault_rate=spec["fault_rate"], max_concurrency=spec["max_concurrency"], output=output,
        )
        plan_log.append({"label": label, "rows": n, **spec})
        total_written += n
        # Ablation runs: only on a small subset to keep cost bounded
        if spec["benchmark"] == "tau3" and spec["fault_rate"] == fault_rates[-1] and spec["max_concurrency"] == concurrencies[0]:
            for ablation in ablations:
                abl_output = output_dir / f"{label}__{ablation}.jsonl"
                abl_methods = ["adagentflow_rt"]
                n2 = _run_one(
                    benchmark=spec["benchmark"], domain=spec["domain"], num_tasks=spec["num_tasks"],
                    num_trials=spec["num_trials"], methods=abl_methods, stress=spec["stress"],
                    fault_rate=spec["fault_rate"], max_concurrency=spec["max_concurrency"],
                    output=abl_output, ablation=ablation,
                )
                plan_log.append({"label": abl_output.stem, "rows": n2, "ablation": ablation, **spec})
                total_written += n2

    (output_dir / "run_plan.json").write_text(json.dumps(plan_log, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"OK: wrote {total_written} JSONL rows across {len(plan_log)} runs in {output_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()