"""tau2-bench / tau3-bench workload adapter.

In external mode, the adapter records the planned shell command and writes
JSONL rows with ``benchmark_adapter_mode="external"`` plus the command in
``external_command``. In mock mode (the default), it generates equivalent
task content via :mod:`experiments.harness.scenarios` so the harness can run
end-to-end without depending on a private benchmark checkout.
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
from experiments.harness.scenarios import generate_tasks


class Tau3BenchmarkAdapter(MockBenchmarkAdapter):
    benchmark_name = "tau3"

    def load_tasks(self, config: Dict[str, Any]) -> Iterable[BenchmarkTask]:
        if not external_requested(config):
            yield from _scenarios_as_benchmark_tasks(self.benchmark_name, config)
            return

        command = self.external_command(config)
        domain = str(config.get("domain", "airline"))
        task_ids = config_task_ids(config)
        num_tasks = int(config.get("num_tasks", len(task_ids) or 1))
        num_trials = int(config.get("num_trials", 1))
        planned_ids = task_ids or [f"{domain}_external_{idx}" for idx in range(num_tasks)]
        for trial_id in range(num_trials):
            for task_id in planned_ids[:num_tasks]:
                yield BenchmarkTask(
                    benchmark=self.benchmark_name,
                    domain=domain,
                    task_id=task_id,
                    trial_id=trial_id,
                    payload={
                        "adapter_mode": "external",
                        "benchmark_repo_path": str(config.get("benchmark_repo_path")),
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

        command = self.external_command(config)
        domain = str(config.get("domain", "airline"))
        task_ids = config_task_ids(config)
        num_tasks = int(config.get("num_tasks", len(task_ids) or 1))
        num_trials = int(config.get("num_trials", 1))
        planned_ids = task_ids or [f"{domain}_agentchange_external_{idx}" for idx in range(num_tasks)]
        for trial_id in range(num_trials):
            for task_id in planned_ids[:num_tasks]:
                yield BenchmarkTask(
                    benchmark=self.benchmark_name,
                    domain=domain,
                    task_id=task_id,
                    trial_id=trial_id,
                    payload={
                        "adapter_mode": "external",
                        "benchmark_repo_path": str(config.get("benchmark_repo_path")),
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
    """Convert scenario tasks into BenchmarkTask rows for the harness."""
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
