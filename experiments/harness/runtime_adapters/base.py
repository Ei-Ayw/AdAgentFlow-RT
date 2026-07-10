"""Runtime adapter interfaces."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from experiments.harness.benchmark_adapters.base import BenchmarkTask


@dataclass
class RuntimeResult:
    benchmark: str
    domain: str
    task_id: str
    trial_id: int
    method: str
    run_id: str
    success: bool
    suite_run: Optional[str] = None
    fault_rate: Optional[float] = None
    max_concurrency: Optional[int] = None
    stress: Optional[str] = None
    ablation: Optional[str] = None
    benchmark_adapter_mode: str = "mock"
    external_command: List[str] = field(default_factory=list)
    native_metrics: Dict[str, Any] = field(default_factory=dict)
    runtime_metrics: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    trajectory_path: Optional[str] = None
    runtime_trace_path: Optional[str] = None
    latency_ms: int = 0
    tool_calls: int = 0
    llm_calls: int = 0
    attempts: int = 1
    injected_faults: List[Dict[str, Any]] = field(default_factory=list)
    recovered: bool = False
    dead_letter: bool = False
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RuntimeAdapter:
    method_name = "base"

    def run_task(
        self,
        task: BenchmarkTask,
        context: Dict[str, Any],
        stressors: list[Any],
        runtime_config: Dict[str, Any],
    ) -> RuntimeResult:
        raise NotImplementedError


def stable_task_seed(task_id: str, method: str) -> int:
    digest = hashlib.sha256(f"{task_id}:{method}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16)
