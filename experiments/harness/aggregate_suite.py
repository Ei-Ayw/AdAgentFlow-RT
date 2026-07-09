"""Aggregate every JSONL result file in a suite directory."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from experiments.harness.aggregate_results import load_results
from experiments.harness.metrics.benchmark_metrics import compute_benchmark_metrics
from experiments.harness.metrics.runtime_metrics import compute_runtime_metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite-dir", required=True)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()

    summaries = summarize_suite(Path(args.suite_dir))
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summaries, indent=2, ensure_ascii=False), encoding="utf-8")


def summarize_suite(suite_dir: Path):
    summaries = []
    for path in sorted(suite_dir.glob("*.jsonl")):
        results = load_results(path)
        if not results:
            continue
        grouped = defaultdict(list)
        for result in results:
            grouped[
                (
                    result.benchmark,
                    result.domain,
                    result.method,
                    result.ablation,
                    result.benchmark_adapter_mode,
                    result.suite_run,
                    result.fault_rate,
                    result.max_concurrency,
                    result.stress,
                )
            ].append(result)
        for (
            benchmark,
            domain,
            method,
            ablation,
            adapter_mode,
            suite_run,
            fault_rate,
            max_concurrency,
            stress,
        ), rows in sorted(grouped.items(), key=lambda item: str(item[0])):
            summaries.append(
                {
                    "source": str(path),
                    "benchmark": benchmark,
                    "domain": domain,
                    "method": method,
                    "ablation": ablation,
                    "benchmark_adapter_mode": adapter_mode,
                    "suite_run": suite_run,
                    "fault_rate": fault_rate,
                    "max_concurrency": max_concurrency,
                    "stress": stress,
                    **compute_benchmark_metrics(rows),
                    **compute_runtime_metrics(rows),
                }
            )
    return summaries


if __name__ == "__main__":
    main()
