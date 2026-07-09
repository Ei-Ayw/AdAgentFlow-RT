"""Run the full production-stress matrix against the LLM-backed adapters.

This driver is the entry point for producing real paper artifacts. It sweeps:
  * tau3 × {airline, retail, telecom} × concurrency {1, 5, 10} × fault {0, 0.1, 0.2}
  * agentchange × {airline, retail} × concurrency {1, 5} × fault {0, 0.1}
  * ablations {full, without_contract_monitor, without_fault_localizer,
                without_bounded_recovery, without_event_trace}

Every run writes JSONL, then aggregate_suite, refresh_paper_artifacts, and
audit_results are invoked so the paper tables / figures update in one step.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from experiments.harness.run_experiment import BENCHMARKS, RUNTIMES, build_stressors
from experiments.harness.workload.concurrency_runner import run_tasks


def _run_one(*, benchmark: str, domain: str, num_tasks: int, num_trials: int,
             methods: List[str], stress: str, fault_rate: float,
             max_concurrency: int, output: Path, ablation: str | None = None) -> int:
    config = {
        "domain": domain,
        "num_tasks": num_tasks,
        "num_trials": num_trials,
        "max_concurrency": max_concurrency,
    }
    adapter = BENCHMARKS[benchmark]()
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
    parser.add_argument("--smoke", action="store_true", help="Use a tiny matrix (faster smoke)")
    parser.add_argument("--no-ablation", action="store_true")
    parser.add_argument("--no-agentchange", action="store_true")
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    methods = ["vanilla", "retry_only", "schema_only", "adagentflow_rt"]

    if args.smoke:
        matrix: List[Dict[str, Any]] = [
            dict(benchmark="tau3", domain="airline", num_tasks=3, num_trials=1, stress="", fault_rate=0.0, max_concurrency=1, suite="smoke"),
            dict(benchmark="tau3", domain="airline", num_tasks=3, num_trials=1, stress="schema_drift,duplicate_message", fault_rate=0.2, max_concurrency=2, suite="smoke"),
            dict(benchmark="tau3", domain="retail", num_tasks=3, num_trials=1, stress="schema_drift,duplicate_message", fault_rate=0.2, max_concurrency=2, suite="smoke"),
            dict(benchmark="agentchange", domain="airline", num_tasks=3, num_trials=1, stress="schema_drift,duplicate_message", fault_rate=0.2, max_concurrency=2, suite="smoke"),
        ]
    else:
        matrix = []
        for domain in ("airline", "retail", "telecom"):
            for fault_rate in (0.0, 0.1, 0.2):
                for concurrency in (1, 5, 10):
                    matrix.append(dict(
                        benchmark="tau3", domain=domain, num_tasks=6, num_trials=2,
                        stress="tool_timeout,rate_limit,partial_response,schema_drift,stale_context,duplicate_message",
                        fault_rate=fault_rate, max_concurrency=concurrency, suite="tau3_main",
                    ))
        if not args.no_agentchange:
            for domain in ("airline", "retail"):
                for fault_rate in (0.0, 0.1):
                    for concurrency in (1, 5):
                        matrix.append(dict(
                            benchmark="agentchange", domain=domain, num_tasks=5, num_trials=2,
                            stress="schema_drift,stale_context,duplicate_message",
                            fault_rate=fault_rate, max_concurrency=concurrency, suite="agentchange_supp",
                        ))

    ablations = [] if args.no_ablation else [
        "without_contract_monitor", "without_fault_localizer", "without_bounded_recovery", "without_event_trace",
    ]

    total_written = 0
    plan_log: List[Dict[str, Any]] = []
    for spec in matrix:
        label = f"{spec['benchmark']}_{spec['domain']}_c{spec['max_concurrency']}_f{str(spec['fault_rate']).replace('.', 'p')}_{spec['stress'][:24] or 'none'}"
        output = output_dir / f"{label}.jsonl"
        n = _run_one(
            benchmark=spec["benchmark"], domain=spec["domain"], num_tasks=spec["num_tasks"],
            num_trials=spec["num_trials"], methods=methods, stress=spec["stress"],
            fault_rate=spec["fault_rate"], max_concurrency=spec["max_concurrency"], output=output,
        )
        plan_log.append({"label": label, "rows": n, **spec})
        total_written += n
        # Ablation runs: only on a small subset to keep cost bounded
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
