"""Aggregate JSONL experiment results into JSON and CSV summaries."""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from experiments.harness.metrics.benchmark_metrics import compute_benchmark_metrics
from experiments.harness.metrics.runtime_metrics import compute_runtime_metrics
from experiments.harness.runtime_adapters.base import RuntimeResult


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="experiments/results/smoke/mock_smoke.jsonl")
    parser.add_argument("--json-output", default="experiments/results/smoke/summary.json")
    parser.add_argument("--csv-output", default="experiments/results/smoke/summary.csv")
    args = parser.parse_args()

    results = load_results(Path(args.input))
    grouped = defaultdict(list)
    for result in results:
        grouped[(result.benchmark, result.domain, result.method)].append(result)

    summaries = []
    for (benchmark, domain, method), rows in sorted(grouped.items()):
        summaries.append(
            {
                "benchmark": benchmark,
                "domain": domain,
                "method": method,
                **compute_benchmark_metrics(rows),
                **compute_runtime_metrics(rows),
            }
        )

    Path(args.json_output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.json_output, "w", encoding="utf-8") as fh:
        json.dump(summaries, fh, indent=2, ensure_ascii=False)
    with open(args.csv_output, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=sorted({key for row in summaries for key in row}))
        writer.writeheader()
        writer.writerows(summaries)


def load_results(path: Path) -> list[RuntimeResult]:
    rows: list[RuntimeResult] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            rows.append(RuntimeResult(**json.loads(line)))
    return rows


if __name__ == "__main__":
    main()
