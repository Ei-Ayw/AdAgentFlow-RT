"""Build a reference set for controlled fault injection.

The reference set is the subset of smoke (no-fault) JSONL rows where
the run produced a fixture-success and a runtime-success with no
contract violation and no recovery action.  These are the trajectories
we will re-run with a single fault injected to measure the causal
effect of each stressor.

The output JSONL is self-contained: every row contains both the
``RuntimeResult`` metrics (so the aggregator can compute deltas
without re-running) and the ``BenchmarkTask`` payload (so the replay
runner can re-invoke ``evaluate_task`` against the same LLM
endpoint, same task content, same task_id).

Run from the repo root:

    .venv/bin/python -m experiments.harness.build_reference_set \\
        --smoke-dir experiments/results/main/real_full_v2/smoke \\
        --output experiments/results/main/real_full_v2/reference_set.jsonl
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from experiments.harness.aggregate_results import load_results
from experiments.harness.external_data import DEFAULT_TAU2_REPO, resolve_agentchange_repo


def _is_clean_reference(result: Any) -> bool:
    """True if the runtime result is a clean reference trajectory.

    A "clean reference" is a no-fault run that the runtime finalised
    without any contract work: no contract violation, no bounded
    recovery action, no injected fault, no dead-letter.  The fixture
    scorer may still disagree (a reference that is off-policy on the
    first attempt is still useful as a causal baseline, because the
    comparison we make is ``replay - reference`` rather than
    ``fixture(replay) == success``).

    The advisor's design calls this a "successful-trajectory fault
    injection": we re-run a trajectory that the runtime processed
    cleanly and measure what happens when one fault is injected.  The
    causal effect is the replay metrics minus the reference metrics;
    the reference itself does not need to be a fixture-success.
    """
    runtime = getattr(result, "runtime_metrics", {}) or {}
    if runtime.get("contract_violations", 0) > 0:
        return False
    if runtime.get("bounded_recovery_actions", 0) > 0:
        return False
    if getattr(result, "injected_faults", []):
        return False
    if getattr(result, "dead_letter", False):
        return False
    return True


def _task_payload_from_adapter(adapter: Any, benchmark: str, domain: str,
                               task_id: str, trial_id: int) -> Dict[str, Any]:
    """Reload the BenchmarkTask that produced this result.

    The benchmark adapter is deterministic given a config, so the same
    (benchmark, domain, task_id, trial_id) tuple always yields the same
    payload.  We probe the adapter with a small config and return the
    matching task.
    """
    config = {
        "domain": domain,
        "num_tasks": 64,
        "num_trials": max(trial_id + 1, 1),
    }
    if benchmark == "tau3" and DEFAULT_TAU2_REPO.exists():
        config["benchmark_repo_path"] = str(DEFAULT_TAU2_REPO)
        config["execution_mode"] = "external"
    elif benchmark == "agentchange":
        repo = resolve_agentchange_repo()
        if repo.exists():
            config["benchmark_repo_path"] = str(repo)
            config["execution_mode"] = "external"
    for task in adapter.load_tasks(config):
        if task.task_id == task_id and task.trial_id == trial_id:
            return {
                "benchmark": task.benchmark,
                "domain": task.domain,
                "task_id": task.task_id,
                "trial_id": task.trial_id,
                "payload": task.payload,
                "native_metrics": task.native_metrics,
                "adapter_mode": task.adapter_mode,
                "external_command": task.external_command,
            }
    return {}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-dir", required=True,
                        help="Directory containing smoke (no-fault) JSONL files")
    parser.add_argument("--output", required=True,
                        help="Output reference_set.jsonl path")
    parser.add_argument("--include-methods", nargs="*",
                        default=["vanilla", "retry_only", "schema_only", "adagentflow_rt"])
    args = parser.parse_args()

    # Lazy-import adapters to avoid a hard dependency on the external
    # benchmark checkout.  The mock adapter is always available; the
    # tau3 / agentchange adapters require a benchmark_repo_path and
    # fall back to the mock adapter in smoke mode.
    from experiments.harness.benchmark_adapters.base import MockBenchmarkAdapter
    from experiments.harness.benchmark_adapters.tau3_adapter import Tau3BenchmarkAdapter
    from experiments.harness.benchmark_adapters.agentchange_adapter import (
        AgentChangeBenchmarkAdapter,
    )

    adapters = {
        "mock": MockBenchmarkAdapter(),
        "tau3": Tau3BenchmarkAdapter(),
        "agentchange": AgentChangeBenchmarkAdapter(),
    }

    smoke_dir = Path(args.smoke_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    seen: set = set()
    reference: List[Dict[str, Any]] = []
    for path in sorted(smoke_dir.glob("*.jsonl")):
        for result in load_results(path):
            if result.method not in args.include_methods:
                continue
            if not _is_clean_reference(result):
                continue
            key = (result.benchmark, result.domain, result.task_id, result.trial_id, result.method)
            if key in seen:
                continue
            seen.add(key)
            adapter = adapters.get(result.benchmark, adapters["mock"])
            task_payload = _task_payload_from_adapter(
                adapter, result.benchmark, result.domain, result.task_id, result.trial_id,
            )
            if not task_payload:
                # Adapter did not produce a matching task; skip.  This
                # is the expected behaviour for the smoke adapter when
                # the smoke result was generated with a different
                # ``num_tasks`` config.
                continue
            row = result.to_dict()
            row["task_payload"] = task_payload
            row["_source_smoke_path"] = str(path)
            reference.append(row)

    with output.open("w", encoding="utf-8") as fh:
        for row in reference:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"wrote {len(reference)} reference rows to {output}")


if __name__ == "__main__":
    main()
