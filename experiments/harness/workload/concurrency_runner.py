"""Simple thread-based concurrency runner for smoke experiments."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List

from experiments.harness.benchmark_adapters.base import BenchmarkTask
from experiments.harness.fault_plans import build_fault_plan
from experiments.harness.runtime_adapters.base import RuntimeAdapter, RuntimeResult


def run_tasks(
    *,
    tasks: Iterable[BenchmarkTask],
    adapter: RuntimeAdapter,
    stressors: list[Any],
    runtime_config: Dict[str, Any],
    max_concurrency: int = 1,
) -> List[RuntimeResult]:
    task_list = list(tasks)
    max_attempts = max(1, int(runtime_config.get("max_retries", 0)) + 1)
    contexts = [
        {
            "fault_plan": [entry.to_dict() for entry in build_fault_plan(task=task, stressors=stressors, max_attempts=max_attempts)],
        }
        for task in task_list
    ]
    if max_concurrency <= 1:
        return [
            adapter.run_task(task, context=context, stressors=stressors, runtime_config=runtime_config)
            for task, context in zip(task_list, contexts)
        ]
    results: List[RuntimeResult] = []
    with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
        futures = [
            pool.submit(adapter.run_task, task, context, stressors, runtime_config)
            for task, context in zip(task_list, contexts)
        ]
        for future in as_completed(futures):
            results.append(future.result())
    return results
