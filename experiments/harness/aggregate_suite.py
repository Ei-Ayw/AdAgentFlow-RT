"""Aggregate every JSONL result file in a suite directory."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from experiments.harness.aggregate_results import load_results
from experiments.harness.metrics.benchmark_metrics import compute_benchmark_metrics
from experiments.harness.metrics.runtime_metrics import compute_runtime_metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite-dir", required=True)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()

    summaries = []
    for path in sorted(Path(args.suite_dir).glob("*.jsonl")):
        results = load_results(path)
        if not results:
            continue
        summaries.append(
            {
                "source": str(path),
                **compute_benchmark_metrics(results),
                **compute_runtime_metrics(results),
            }
        )
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summaries, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
