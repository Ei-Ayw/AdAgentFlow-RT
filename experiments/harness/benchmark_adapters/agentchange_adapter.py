"""AgentChangeBench workload adapter skeleton."""
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


class AgentChangeBenchmarkAdapter(MockBenchmarkAdapter):
    benchmark_name = "agentchange"

    def load_tasks(self, config: Dict[str, Any]) -> Iterable[BenchmarkTask]:
        if not external_requested(config):
            for task in super().load_tasks(config):
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
