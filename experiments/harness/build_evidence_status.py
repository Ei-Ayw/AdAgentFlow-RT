"""Regenerate paper/aamas2026/tables/evidence_status.csv with proper CSV quoting.

The previous hand-maintained file contained unquoted commas in the ``gate``
column (lines 7-10), which broke ``pandas.read_csv``. This script
re-emits the same claim / artifact / status / gate table using
``csv.DictWriter`` so any embedded commas are quoted and the file is
parseable by both the stdlib csv module and pandas.

Run from the repo root:

    .venv/bin/python -m experiments.harness.build_evidence_status
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import List, Dict

# Claim-level evidence rows. These mirror the paper's evidence_status
# table. Edit here rather than the CSV file when content changes.
EVIDENCE_ROWS: List[Dict[str, str]] = [
    {
        "claim": "End-to-end harness execution",
        "artifact": "experiments/results/main/real_full_v2/*.jsonl",
        "status": "complete",
        "gate": "run_real_external.py against Qwen3-8B vLLM",
    },
    {
        "claim": "Runtime metrics and traces",
        "artifact": "experiments/results/main/real_full_v2/summary.json",
        "status": "complete",
        "gate": "aggregate_suite over 116 summary rows",
    },
    {
        "claim": "Main tau2/tau3 benchmark claims",
        "artifact": "experiments/results/main/real_full_v2/*tau3*.jsonl",
        "status": "complete",
        "gate": "external benchmark_repo_path + audit_results --require-external-main",
    },
    {
        "claim": "AgentChangeBench recovery claims",
        "artifact": "experiments/results/main/real_full_v2/*agentchange*.jsonl",
        "status": "complete",
        "gate": "external benchmark_repo_path + audit_results --require-agentchange",
    },
    {
        "claim": "Paper tables and figures",
        "artifact": "paper/aamas2026/tables and figs",
        "status": "complete",
        "gate": "refresh_paper_artifacts from real_full_v2 summary",
    },
    {
        "claim": "Ablation study (4 ablations)",
        "artifact": "experiments/results/main/real_full_v2/*__without_*.jsonl",
        "status": "complete",
        "gate": (
            "4 ablations: without_contract_monitor; without_fault_localizer; "
            "without_bounded_recovery; without_event_trace"
        ),
    },
    {
        "claim": "Stress harness",
        "artifact": "experiments/harness/stressors/",
        "status": "complete",
        "gate": (
            "7 stressors: tool_timeout; rate_limit; partial_response; "
            "schema_drift; stale_context; duplicate_message; worker_crash"
        ),
    },
    {
        "claim": "Runtime strategies",
        "artifact": "experiments/harness/runtime_adapters/",
        "status": "complete",
        "gate": "4 strategies: vanilla; retry_only; schema_only; adagentflow_rt",
    },
    {
        "claim": "Real-LLM evidence",
        "artifact": "experiments/results/main/real_full_v2/summary.json",
        "status": "complete",
        "gate": (
            "1392 JSONL rows across 39 runs on Qwen3-8B (vLLM 0.23.0; "
            "--gpu-memory-utilization 0.20; ~4h total)"
        ),
    },
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="paper/aamas2026/tables/evidence_status.csv",
    )
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    fields = ["claim", "artifact", "status", "gate"]
    with output.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for row in EVIDENCE_ROWS:
            writer.writerow(row)
    print(f"wrote {len(EVIDENCE_ROWS)} rows to {output}")


if __name__ == "__main__":
    main()
