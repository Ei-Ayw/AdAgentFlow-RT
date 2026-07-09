"""Plan or execute experiment suites without running full experiments by default."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from experiments.harness.config import config_list, load_simple_config
from experiments.harness.run_matrix import run_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite-config", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    suite = load_simple_config(args.suite_config)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    plan = build_suite_plan(suite, output_dir=output_dir)
    manifest_path = output_dir / "suite_manifest.json"
    manifest_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.execute:
        for item in plan["runs"]:
            run_config(item["config"], output_path=Path(item["output"]), append=False)


def build_suite_plan(suite: Dict[str, Any], *, output_dir: Path) -> Dict[str, Any]:
    runs: List[Dict[str, Any]] = []
    suite_name = str(suite.get("suite_name", "suite"))
    benchmarks = config_list(suite, "benchmarks", ["tau3"])
    domains = config_list(suite, "domains", ["airline"])
    concurrencies = config_list(suite, "concurrency_values", [1])
    fault_rates = config_list(suite, "fault_rates", [0.0])
    stress_profiles = config_list(suite, "stress_profiles", ["none"])
    methods = config_list(suite, "methods", ["vanilla", "retry_only", "schema_only", "adagentflow_rt"])
    ablations = config_list(suite, "ablations", [None])

    for benchmark in benchmarks:
        for domain in domains:
            for concurrency in concurrencies:
                for fault_rate in fault_rates:
                    for stress_profile in stress_profiles:
                        for ablation in ablations:
                            if ablation in {"null", "none", ""}:
                                ablation = None
                            config = {
                                "suite_run": suite_name,
                                "benchmark": benchmark,
                                "domain": domain,
                                "num_tasks": suite.get("num_tasks", 3),
                                "num_trials": suite.get("num_trials", 1),
                                "max_concurrency": concurrency,
                                "fault_rate": fault_rate,
                                "stress": _stress_value(stress_profile),
                                "methods": methods,
                                "max_retries": suite.get("max_retries", 2),
                                "ablation": ablation,
                            }
                            if suite.get("execution_mode"):
                                config["execution_mode"] = suite["execution_mode"]
                            if suite.get("benchmark_repo_path"):
                                config["benchmark_repo_path"] = suite["benchmark_repo_path"]
                            if suite.get("agent_llm"):
                                config["agent_llm"] = suite["agent_llm"]
                            if suite.get("user_llm"):
                                config["user_llm"] = suite["user_llm"]
                            if suite.get("benchmark_command"):
                                config["benchmark_command"] = suite["benchmark_command"]
                            if suite.get("output_dir"):
                                config["output_dir"] = suite["output_dir"]
                            if suite.get("task_ids"):
                                config["task_ids"] = suite["task_ids"]
                            label = _run_label(config)
                            output = output_dir / f"{label}.jsonl"
                            runs.append(
                                {
                                    "label": label,
                                    "output": str(output),
                                    "config": config,
                                }
                            )
    return {
        "suite_name": suite_name,
        "run_count": len(runs),
        "execute_by_default": False,
        "runs": runs,
    }


def _run_label(config: Dict[str, Any]) -> str:
    parts = [
        str(config["benchmark"]),
        str(config["domain"]),
        f"c{config['max_concurrency']}",
        f"f{str(config['fault_rate']).replace('.', 'p')}",
        str(config["stress"] or "none"),
    ]
    if config.get("ablation"):
        parts.append(str(config["ablation"]))
    return "_".join(parts).replace("/", "_").replace(",", "-")


def _stress_value(profile: Any) -> str:
    if profile is None:
        return ""
    profile = str(profile)
    aliases = {
        "none": "",
        "low": "tool_timeout,schema_drift,duplicate_message",
        "medium": "tool_timeout,rate_limit,partial_response,schema_drift,stale_context,duplicate_message",
        "high": "tool_timeout,rate_limit,partial_response,schema_drift,stale_context,duplicate_message,worker_crash",
        "schema_drift_all": "schema_drift",
    }
    return aliases.get(profile, profile)


if __name__ == "__main__":
    main()
