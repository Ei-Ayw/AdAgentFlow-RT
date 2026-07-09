"""tau2-bench / tau3-bench workload adapter skeleton."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable

from experiments.harness.benchmark_adapters.base import BenchmarkTask, MockBenchmarkAdapter


class Tau3BenchmarkAdapter(MockBenchmarkAdapter):
    benchmark_name = "tau3"

    def load_tasks(self, config: Dict[str, Any]) -> Iterable[BenchmarkTask]:
        repo_path = config.get("benchmark_repo_path")
        if repo_path and not Path(repo_path).exists():
            raise RuntimeError(
                "tau2-bench / tau3-bench repo was not found. "
                "Set benchmark_repo_path to an installed checkout or omit it for mock smoke tasks."
            )
        # Until the external package is installed, deterministic mock tasks keep
        # the harness runnable while preserving the normalized output contract.
        yield from super().load_tasks(config)
