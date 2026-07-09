"""AgentChangeBench workload adapter skeleton."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable

from experiments.harness.benchmark_adapters.base import BenchmarkTask, MockBenchmarkAdapter


class AgentChangeBenchmarkAdapter(MockBenchmarkAdapter):
    benchmark_name = "agentchange"

    def load_tasks(self, config: Dict[str, Any]) -> Iterable[BenchmarkTask]:
        repo_path = config.get("benchmark_repo_path")
        if repo_path and not Path(repo_path).exists():
            raise RuntimeError(
                "AgentChangeBench repo was not found. "
                "Set benchmark_repo_path to an installed checkout or omit it for mock smoke tasks."
            )
        for task in super().load_tasks(config):
            task.native_metrics.update({"TSR": None, "TUE": None, "TCRR": None, "GSRT": None})
            yield task
