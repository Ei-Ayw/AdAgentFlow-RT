"""Run an experiment from harness config files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from experiments.harness.config import config_methods, config_stressors, load_simple_config
from experiments.harness.run_experiment import BENCHMARKS, RUNTIMES, build_stressors
from experiments.harness.workload.concurrency_runner import run_tasks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--stress-config", default=None)
    parser.add_argument("--overlay-config", action="append", default=[])
    parser.add_argument("--output", required=True)
    parser.add_argument("--append", action="store_true")
    args = parser.parse_args()

    experiment_config = load_simple_config(args.config)
    stress_config = load_simple_config(args.stress_config) if args.stress_config else {}
    merged = {**experiment_config, **{k: v for k, v in stress_config.items() if v is not None}}
    for overlay_path in args.overlay_config:
        overlay = load_simple_config(overlay_path)
        merged.update({k: v for k, v in overlay.items() if v is not None})

    benchmark_name = str(merged.get("benchmark", "mock"))
    if benchmark_name not in BENCHMARKS:
        raise KeyError(f"unknown benchmark: {benchmark_name}")
    benchmark = BENCHMARKS[benchmark_name]()
    tasks = list(benchmark.load_tasks(merged))
    stressors = build_stressors(",".join(config_stressors(merged)), float(merged.get("fault_rate", 0.0) or 0.0))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if args.append else "w"
    with output_path.open(mode, encoding="utf-8") as fh:
        for method in config_methods(merged):
            if method not in RUNTIMES:
                raise KeyError(f"unknown runtime method: {method}")
            runtime_config = {
                "max_retries": int(merged.get("max_retries", 2) or 0),
                "ablation": merged.get("ablation"),
            }
            runtime = RUNTIMES[method]()
            results = run_tasks(
                tasks=tasks,
                adapter=runtime,
                stressors=stressors,
                runtime_config=runtime_config,
                max_concurrency=int(merged.get("max_concurrency", 1) or 1),
            )
            for result in results:
                fh.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
