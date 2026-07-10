"""Validate experiment suite configs before execution."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from experiments.harness.config import config_list, load_simple_config
from experiments.harness.run_experiment import BENCHMARKS, RUNTIMES, STRESSORS
from experiments.harness.run_suite import build_suite_plan


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite-config", required=True)
    parser.add_argument("--output-dir", default="experiments/results/validation")
    parser.add_argument("--json-output", default=None)
    args = parser.parse_args()

    suite = load_simple_config(args.suite_config)
    report = validate_suite_config(suite, output_dir=Path(args.output_dir))
    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if not report["ok"]:
        for error in report["errors"]:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    print(
        f"OK: {report['suite_name']} has {report['run_count']} planned runs "
        f"covering {report['benchmarks']} benchmarks and {report['methods']} methods."
    )


def validate_suite_config(suite: Dict[str, Any], *, output_dir: Path) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    plan = build_suite_plan(suite, output_dir=output_dir)

    benchmarks = sorted({str(item["config"].get("benchmark")) for item in plan["runs"]})
    methods = sorted({str(method) for method in config_list(suite, "methods", [])})
    stressors = sorted(_suite_stressors(plan))

    for benchmark in benchmarks:
        if benchmark not in BENCHMARKS:
            errors.append(f"unknown benchmark: {benchmark}")
    for method in methods:
        if method not in RUNTIMES:
            errors.append(f"unknown runtime method: {method}")
    for stressor in stressors:
        if stressor and stressor not in STRESSORS:
            errors.append(f"unknown stressor: {stressor}")

    if plan["run_count"] == 0:
        errors.append("suite expands to zero runs")
    if _external_requested(suite):
        _validate_external_suite(suite, errors=errors, warnings=warnings)
    else:
        warnings.append("suite uses deterministic mock benchmark mode; external benchmark results are not claimed")

    expected_runs = _expected_run_count(suite)
    if expected_runs != plan["run_count"]:
        errors.append(f"run_count mismatch: expected {expected_runs}, got {plan['run_count']}")

    return {
        "ok": not errors,
        "suite_name": plan["suite_name"],
        "run_count": plan["run_count"],
        "expected_run_count": expected_runs,
        "benchmarks": benchmarks,
        "domains": sorted({str(item["config"].get("domain")) for item in plan["runs"]}),
        "methods": methods,
        "stressors": stressors,
        "errors": errors,
        "warnings": warnings,
    }


def _suite_stressors(plan: Dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for item in plan["runs"]:
        for name in str(item["config"].get("stress") or "").split(","):
            if name:
                names.add(name)
    return names


def _external_requested(suite: Dict[str, Any]) -> bool:
    return bool(suite.get("benchmark_repo_path") or suite.get("execution_mode") == "external")


def _validate_external_suite(suite: Dict[str, Any], *, errors: List[str], warnings: List[str]) -> None:
    repo_path = suite.get("benchmark_repo_path")
    if not repo_path:
        errors.append("external suite requires benchmark_repo_path")
        return
    path = Path(str(repo_path)).expanduser()
    if not path.exists():
        errors.append(f"benchmark_repo_path does not exist: {path}")
    if not suite.get("benchmark_command") and not (path / "pyproject.toml").exists():
        warnings.append("external suite has no benchmark_command and repo has no pyproject.toml")


def _expected_run_count(suite: Dict[str, Any]) -> int:
    keys = [
        ("benchmarks", ["tau3"]),
        ("domains", ["airline"]),
        ("concurrency_values", [1]),
        ("fault_rates", [0.0]),
        ("stress_profiles", ["none"]),
        ("ablations", [None]),
    ]
    total = 1
    for key, default in keys:
        total *= len(config_list(suite, key, default))
    return total


if __name__ == "__main__":
    main()
