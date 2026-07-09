"""τ³-bench (a.k.a. τ²-bench) workload adapter.

In external mode the adapter loads the *real* τ³-bench task fixtures shipped
with the public repo at ``data/external/tau2-bench`` (see
``experiments/harness/external_data.py``). In mock mode it falls back to the
deterministic synthetic scenarios used for smoke runs.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable

from experiments.harness.benchmark_adapters.base import (
    BenchmarkTask,
    MockBenchmarkAdapter,
    command_prefix,
    config_task_ids,
    external_requested,
    require_benchmark_repo,
)
from experiments.harness.external_data import (
    DEFAULT_TAU2_REPO,
    ExternalTask,
    load_tau3_tasks,
    resolve_agentchange_repo,
)
from experiments.harness.scenarios import generate_tasks


class Tau3BenchmarkAdapter(MockBenchmarkAdapter):
    benchmark_name = "tau3"

    def load_tasks(self, config: Dict[str, Any]) -> Iterable[BenchmarkTask]:
        if not external_requested(config):
            yield from _scenarios_as_benchmark_tasks(self.benchmark_name, config)
            return

        # External mode: load real τ³-bench task fixtures.
        repo = config.get("benchmark_repo_path") or str(DEFAULT_TAU2_REPO)
        from pathlib import Path
        domain = str(config.get("domain", "airline"))
        num_tasks = int(config.get("num_tasks", 6))
        num_trials = int(config.get("num_trials", 1))
        external = load_tau3_tasks(
            repo_path=Path(str(repo)),
            domain=domain,
            num_tasks=num_tasks,
            num_trials=num_trials,
        )
        for ext in external:
            yield _external_to_benchmark_task(ext)

        # External mode also records a CLI plan row for downstream import (when
        # the tau2 CLI is available; if it isn't, the runbook's import path
        # already covers normalizing native benchmark output).
        try:
            command = self.external_command(config)
        except RuntimeError:
            return
        task_ids = config_task_ids(config) or [ext.task_id for ext in external]
        for trial_id in range(num_trials):
            for task_id in task_ids[:num_tasks]:
                yield BenchmarkTask(
                    benchmark=self.benchmark_name,
                    domain=domain,
                    task_id=task_id,
                    trial_id=trial_id,
                    payload={
                        "adapter_mode": "external",
                        "benchmark_repo_path": str(repo),
                        "external_command": command,
                    },
                    native_metrics={"policy_compliance_expected": True},
                    adapter_mode="external",
                    external_command=command,
                )

    def external_command(self, config: Dict[str, Any]) -> list[str]:
        repo = require_benchmark_repo(config, "tau2-bench / tau3-bench")
        command = command_prefix(repo, config.get("benchmark_command"))
        command.extend(
            [
                "run",
                "--domain",
                str(config.get("domain", "airline")),
                "--agent-llm",
                str(config.get("agent_llm", "gpt-4.1")),
                "--user-llm",
                str(config.get("user_llm", "gpt-4.1")),
                "--num-trials",
                str(config.get("num_trials", 1)),
                "--num-tasks",
                str(config.get("num_tasks", 1)),
            ]
        )
        task_ids = config_task_ids(config)
        if task_ids:
            command.extend(["--task-ids", ",".join(task_ids)])
        if config.get("output_dir"):
            command.extend(["--output-dir", str(config["output_dir"])])
        return command


class AgentChangeBenchmarkAdapter(MockBenchmarkAdapter):
    benchmark_name = "agentchange"

    def load_tasks(self, config: Dict[str, Any]) -> Iterable[BenchmarkTask]:
        if not external_requested(config):
            for task in _scenarios_as_benchmark_tasks(self.benchmark_name, config):
                task.native_metrics.update({"TSR": None, "TUE": None, "TCRR": None, "GSRT": None})
                yield task
            return

        from pathlib import Path
        repo = config.get("benchmark_repo_path") or str(resolve_agentchange_repo())
        domain = str(config.get("domain", "airline"))
        num_tasks = int(config.get("num_tasks", 5))
        num_trials = int(config.get("num_trials", 1))
        external = load_agentchange_tasks(
            repo_path=Path(str(repo)),
            domain=domain,
            num_tasks=num_tasks,
            num_trials=num_trials,
        )
        for ext in external:
            yield _external_to_benchmark_task(ext)

        try:
            command = self.external_command(config)
        except RuntimeError:
            return
        task_ids = config_task_ids(config) or [ext.task_id for ext in external]
        for trial_id in range(num_trials):
            for task_id in task_ids[:num_tasks]:
                yield BenchmarkTask(
                    benchmark=self.benchmark_name,
                    domain=domain,
                    task_id=task_id,
                    trial_id=trial_id,
                    payload={
                        "adapter_mode": "external",
                        "benchmark_repo_path": str(repo),
                        "external_command": command,
                    },
                    native_metrics={
                        "policy_compliance_expected": True,
                        "TSR": None,
                        "TUE": None,
                        "TCRR": None,
                        "GSRT": None,
                    },
                    adapter_mode="external",
                    external_command=command,
                )

    def external_command(self, config: Dict[str, Any]) -> list[str]:
        repo = require_benchmark_repo(config, "AgentChangeBench")
        command = command_prefix(repo, config.get("benchmark_command"))
        command.extend(
            [
                "run",
                "--domain",
                str(config.get("domain", "airline")),
                "--agent-llm",
                str(config.get("agent_llm", "gpt-4.1")),
                "--user-llm",
                str(config.get("user_llm", "gpt-4.1")),
                "--num-trials",
                str(config.get("num_trials", 1)),
                "--num-tasks",
                str(config.get("num_tasks", 1)),
            ]
        )
        task_ids = config_task_ids(config)
        if task_ids:
            command.extend(["--task-ids", ",".join(task_ids)])
        if config.get("output_dir"):
            command.extend(["--output-dir", str(config["output_dir"])])
        return command


def _scenarios_as_benchmark_tasks(benchmark: str, config: Dict[str, Any]) -> Iterable[BenchmarkTask]:
    """Convert scenario tasks into BenchmarkTask rows for the harness (mock mode)."""
    domain = str(config.get("domain", "airline"))
    num_tasks = int(config.get("num_tasks", 3))
    num_trials = int(config.get("num_trials", 1))
    scenarios = generate_tasks(benchmark=benchmark, domain=domain, num_tasks=num_tasks, num_trials=num_trials)
    for sc in scenarios:
        yield BenchmarkTask(
            benchmark=sc.benchmark,
            domain=sc.domain,
            task_id=sc.task_id,
            trial_id=0,
            payload={
                "customer_goal": sc.customer_goal,
                "expected_resolution": sc.expected_resolution,
                "expected_policy_compliant": sc.expected_policy_compliant,
                "tools": list(sc.tools),
                "difficulty": sc.difficulty,
                "goal_change": sc.goal_change,
                "change_target_goal": sc.change_target_goal,
                "expected_tool_sequence": list(sc.expected_tool_sequence),
                "adapter_mode": "mock",
            },
            native_metrics={
                "policy_compliance_expected": sc.expected_policy_compliant,
                "TUE": None,
                "TSR": None,
                "TCRR": None,
                "GSRT": None,
            },
            adapter_mode="mock",
        )


def _external_to_benchmark_task(ext: ExternalTask) -> BenchmarkTask:
    """Convert a normalized external task into a BenchmarkTask row."""
    return BenchmarkTask(
        benchmark=ext.benchmark,
        domain=ext.domain,
        task_id=ext.task_id,
        trial_id=0,
        payload={
            "_benchmark": ext.benchmark,
            "_task_id": ext.task_id,
            "domain": ext.domain,
            "customer_goal": ext.customer_goal,
            "policy_text": ext.policy_text,
            "tools": list(ext.available_tools),
            "expected_tool_sequence": list(ext.expected_tool_sequence),
            "expected_policy_compliant": ext.expected_policy_compliant,
            "goal_change": ext.goal_change,
            "change_target_goal": ext.change_target_goal,
            "nl_assertions": list(ext.nl_assertions),
            "evaluation_basis": ext.evaluation_basis,
            "adapter_mode": "external",
        },
        native_metrics={
            "policy_compliance_expected": ext.expected_policy_compliant,
            "TUE": None,
            "TSR": None,
            "TCRR": None,
            "GSRT": None,
            "evaluation_basis": ext.evaluation_basis,
        },
        adapter_mode="external",
    )


# AgentChangeBench loader re-exported for adapter convenience
def load_agentchange_tasks(*, repo_path=None, domain: str, num_tasks: int = 50, num_trials: int = 1):
    from experiments.harness.external_data import load_agentchange_tasks as _load
    from pathlib import Path
    return _load(repo_path=Path(str(repo_path)) if repo_path else resolve_agentchange_repo(),
                 domain=domain, num_tasks=num_tasks, num_trials=num_trials)