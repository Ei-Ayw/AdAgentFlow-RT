"""Benchmark adapter interfaces and deterministic mock workload."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class BenchmarkTask:
    benchmark: str
    domain: str
    task_id: str
    trial_id: int
    payload: Dict[str, Any] = field(default_factory=dict)
    native_metrics: Dict[str, Any] = field(default_factory=dict)


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
                    },
                    native_metrics={"policy_compliance_expected": True},
                )


def materialize_tasks(adapter: BenchmarkAdapter, config: Dict[str, Any]) -> List[BenchmarkTask]:
    return list(adapter.load_tasks(config))
