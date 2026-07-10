"""Run the controlled fault-injection experiment.

For each reference trajectory (a clean smoke run that produced a
fixture-success and runtime-success) we re-run the task with exactly
one of the five stressors injected, and record the causal outcome
metrics.  See ``docs/contracts/controlled_fault_injection_design.md``
for the design.

The reference set is built by ``build_reference_set.py`` and includes
the full task payload so this runner can re-invoke ``evaluate_task``
against the same LLM endpoint without re-importing any benchmark
data.

Run from the repo root (after the reference set is built):

    .venv/bin/python -m experiments.harness.controlled_fault_injection \\
        --reference-set experiments/results/main/real_full_v2/reference_set.jsonl \\
        --output-dir experiments/results/main/real_full_v2/controlled_fault

The output is one JSONL file per stressor so the aggregator can
compute the per-cell means independently of the runtime path.
"""
from __future__ import annotations

import argparse
import json
import hashlib
from dataclasses import fields
from pathlib import Path
from typing import Any, Dict, List

from experiments.harness.runtime_adapters.base import RuntimeResult
from experiments.harness.runtime_adapters._core import evaluate_task
from experiments.harness.benchmark_adapters.base import BenchmarkTask
from experiments.harness.stressors.duplicate_message import DuplicateMessageStressor
from experiments.harness.stressors.partial_response import PartialResponseStressor
from experiments.harness.stressors.schema_drift import SchemaDriftStressor
from experiments.harness.stressors.stale_context import StaleContextStressor
from experiments.harness.stressors.tool_timeout import ToolTimeoutStressor


STRESSORS = {
    "schema_drift": SchemaDriftStressor,
    "stale_context": StaleContextStressor,
    "partial_response": PartialResponseStressor,
    "duplicate_message": DuplicateMessageStressor,
    "tool_timeout": ToolTimeoutStressor,
}


def _seed(task_id: str, stressor_name: str) -> int:
    digest = hashlib.sha256(f"{task_id}:{stressor_name}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _runtime_result_from_row(row: Dict[str, Any]) -> RuntimeResult:
    allowed = {f.name for f in fields(RuntimeResult)}
    return RuntimeResult(**{k: v for k, v in row.items() if k in allowed})


def _reference_metrics(result: RuntimeResult) -> Dict[str, Any]:
    return {
        "fixture_success": result.native_metrics.get("task_success") is True,
        "runtime_success": result.success and not result.dead_letter,
        "dead_letter": result.dead_letter,
        "contract_violations": int(result.runtime_metrics.get("contract_violations", 0)),
        "bounded_recovery_actions": int(result.runtime_metrics.get("bounded_recovery_actions", 0)),
        "contaminated_artifact_count": int(result.runtime_metrics.get("contaminated_artifact_count", 0)),
    }


def _benchmark_task_from_row(row: Dict[str, Any]) -> BenchmarkTask:
    payload = row.get("task_payload") or {}
    return BenchmarkTask(
        benchmark=payload.get("benchmark", row.get("benchmark", "")),
        domain=payload.get("domain", row.get("domain", "")),
        task_id=payload.get("task_id", row.get("task_id", "")),
        trial_id=int(payload.get("trial_id", row.get("trial_id", 0))),
        payload=payload.get("payload") or {},
        native_metrics=payload.get("native_metrics") or {},
        adapter_mode=payload.get("adapter_mode", row.get("benchmark_adapter_mode", "mock")),
        external_command=payload.get("external_command") or [],
    )


def _replay_with_fault(reference: Dict[str, Any], stressor_name: str) -> Dict[str, Any]:
    stressor_cls = STRESSORS[stressor_name]
    seed = _seed(reference["task_id"], stressor_name)
    stressor = stressor_cls(rate=1.0, seed=seed)
    runtime_config = {
        "ablation": reference.get("ablation"),
        "max_retries": 2,
    }
    task = _benchmark_task_from_row(reference)
    result = evaluate_task(
        task=task,
        method=reference["method"],
        seed=seed,
        stressors=[stressor],
        runtime_config=runtime_config,
    )
    ref = reference.get("_reference_metrics") or _reference_metrics(
        _runtime_result_from_row(reference)
    )
    events = list(result.events or [])
    has_contract_violation = any(e.get("event_type") == "contract.violated" for e in events)
    has_fault_localized = any(e.get("event_type") == "fault.localized" for e in events)
    bounded_recovery_used = (
        int(result.runtime_metrics.get("bounded_recovery_actions", 0)) > 0
    )
    contaminated_artifact_count = int(
        result.runtime_metrics.get("contaminated_artifact_count", 0)
    )
    return {
        "source_reference": reference.get("_source_smoke_path"),
        "task_id": reference["task_id"],
        "trial_id": reference["trial_id"],
        "benchmark": result.benchmark,
        "domain": result.domain,
        "method": result.method,
        "ablation": reference.get("ablation"),
        "stressor": stressor_name,
        "seed": seed,
        "containment": has_contract_violation or has_fault_localized,
        "bounded_recovery_used": bounded_recovery_used,
        "fixture_success": result.native_metrics.get("task_success") is True,
        "runtime_success": result.success and not result.dead_letter,
        "dead_letter": result.dead_letter,
        "contaminated_artifact_count": contaminated_artifact_count,
        "delta_contaminated_artifact_count": (
            contaminated_artifact_count - ref["contaminated_artifact_count"]
        ),
        "delta_contract_violations": (
            int(result.runtime_metrics.get("contract_violations", 0))
            - ref["contract_violations"]
        ),
        "over_rejection": bool(
            result.dead_letter and result.native_metrics.get("task_success") is True
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-set", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--stressors", nargs="*", default=list(STRESSORS))
    parser.add_argument("--max-references", type=int, default=None,
                        help="Optional cap on the number of reference trajectories "
                             "to replay (for smoke tests).")
    args = parser.parse_args()

    reference_set = Path(args.reference_set)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    references: List[Dict[str, Any]] = []
    with reference_set.open("r", encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            row["_reference_metrics"] = _reference_metrics(_runtime_result_from_row(row))
            references.append(row)
    if args.max_references is not None:
        references = references[: args.max_references]

    written = 0
    for stressor in args.stressors:
        out_path = output_dir / f"controlled_{stressor}.jsonl"
        with out_path.open("w", encoding="utf-8") as fh:
            for reference in references:
                outcome = _replay_with_fault(reference, stressor)
                fh.write(json.dumps(outcome, ensure_ascii=False) + "\n")
                written += 1
        print(f"wrote {len(references)} rows to {out_path}")
    print(f"DONE — {written} causal-outcome rows total")


if __name__ == "__main__":
    main()
