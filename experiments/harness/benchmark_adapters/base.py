"""Benchmark adapter interfaces and deterministic mock workload."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shutil
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class BenchmarkTask:
    benchmark: str
    domain: str
    task_id: str
    trial_id: int
    payload: Dict[str, Any] = field(default_factory=dict)
    native_metrics: Dict[str, Any] = field(default_factory=dict)
    adapter_mode: str = "mock"
    external_command: List[str] = field(default_factory=list)


@dataclass
class BenchmarkResult:
    benchmark: str
    domain: str
    task_id: str
    trial_id: int
    success: bool
    native_metrics: Dict[str, Any] = field(default_factory=dict)
    trajectory_path: Optional[str] = None
    runtime_trace_path: Optional[str] = None
    latency_ms: int = 0
    tool_calls: int = 0
    llm_calls: int = 0
    error: Optional[str] = None


class BenchmarkAdapter:
    benchmark_name = "base"

    def load_tasks(self, config: Dict[str, Any]) -> Iterable[BenchmarkTask]:
        raise NotImplementedError

    def external_command(self, config: Dict[str, Any]) -> List[str]:
        raise NotImplementedError


class MockBenchmarkAdapter(BenchmarkAdapter):
    benchmark_name = "mock"

    def load_tasks(self, config: Dict[str, Any]) -> Iterable[BenchmarkTask]:
        domain = str(config.get("domain", "airline"))
        num_tasks = int(config.get("num_tasks", 3))
        num_trials = int(config.get("num_trials", 1))
        for trial_id in range(num_trials):
            for idx in range(num_tasks):
                yield BenchmarkTask(
                    benchmark=self.benchmark_name,
                    domain=domain,
                    task_id=f"{domain}_task_{idx}",
                    trial_id=trial_id,
                    payload={
                        "customer_goal": f"resolve {domain} request {idx}",
                        "difficulty": "smoke",
                        "adapter_mode": "mock",
                    },
                    native_metrics={"policy_compliance_expected": True},
                    adapter_mode="mock",
                )


def materialize_tasks(adapter: BenchmarkAdapter, config: Dict[str, Any]) -> List[BenchmarkTask]:
    return list(adapter.load_tasks(config))


def external_requested(config: Dict[str, Any]) -> bool:
    return bool(config.get("benchmark_repo_path") or config.get("execution_mode") == "external")


def require_benchmark_repo(config: Dict[str, Any], benchmark_label: str) -> Path:
    repo_path = config.get("benchmark_repo_path")
    if not repo_path:
        raise RuntimeError(
            f"{benchmark_label} external mode requires benchmark_repo_path. "
            "Omit execution_mode/benchmark_repo_path for deterministic mock tasks."
        )
    path = Path(str(repo_path)).expanduser().resolve()
    if not path.exists():
        raise RuntimeError(
            f"{benchmark_label} repo was not found at {path}. "
            "Set benchmark_repo_path to an installed checkout or omit it for mock smoke tasks."
        )
    return path


def command_prefix(repo_path: Path, configured_command: Optional[str] = None) -> List[str]:
    if configured_command:
        return configured_command.split()
    if shutil.which("tau2"):
        return ["tau2"]
    if shutil.which("uv") and (repo_path / "pyproject.toml").exists():
        return ["uv", "run", "tau2"]
    raise RuntimeError(
        "No tau2 command is available. Install the benchmark CLI, or run from a repo "
        "with pyproject.toml and uv installed. Omit benchmark_repo_path for mock smoke tasks."
    )


def config_task_ids(config: Dict[str, Any]) -> List[str]:
    task_ids = config.get("task_ids") or []
    if isinstance(task_ids, str):
        return [part.strip() for part in task_ids.split(",") if part.strip()]
    return [str(task_id) for task_id in task_ids]
