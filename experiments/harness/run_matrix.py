"""Run an experiment from harness config files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

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

    run_config(merged, output_path=Path(args.output), append=args.append)


def run_config(config: Dict[str, Any], *, output_path: Path, append: bool = False) -> List[Dict[str, Any]]:
    benchmark_name = str(config.get("benchmark", "mock"))
    if benchmark_name not in BENCHMARKS:
        raise KeyError(f"unknown benchmark: {benchmark_name}")
    benchmark = BENCHMARKS[benchmark_name]()
    tasks = list(benchmark.load_tasks(config))
    stress_names = config_stressors(config)
    stressors = build_stressors(",".join(stress_names), float(config.get("fault_rate", 0.0) or 0.0))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    written: List[Dict[str, Any]] = []
    with output_path.open(mode, encoding="utf-8") as fh:
        for method in config_methods(config):
            if method not in RUNTIMES:
                raise KeyError(f"unknown runtime method: {method}")
            runtime_config = {
                "max_retries": int(config.get("max_retries", 2) or 0),
                "ablation": config.get("ablation"),
            }
            runtime = RUNTIMES[method]()
            results = run_tasks(
                tasks=tasks,
                adapter=runtime,
                stressors=stressors,
                runtime_config=runtime_config,
                max_concurrency=int(config.get("max_concurrency", 1) or 1),
            )
            for result in results:
                row = result.to_dict()
                row["suite_run"] = config.get("suite_run")
                row["fault_rate"] = config.get("fault_rate", 0.0)
                row["max_concurrency"] = config.get("max_concurrency", 1)
                row["stress"] = ",".join(stress_names)
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                written.append(row)
    return written


if __name__ == "__main__":
    main()
