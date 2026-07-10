"""Simple thread-based concurrency runner for smoke experiments."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List

from experiments.harness.benchmark_adapters.base import BenchmarkTask
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
    if max_concurrency <= 1:
        return [
            adapter.run_task(task, context={}, stressors=stressors, runtime_config=runtime_config)
            for task in task_list
        ]
    results: List[RuntimeResult] = []
    with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
        futures = [
            pool.submit(adapter.run_task, task, {}, stressors, runtime_config)
            for task in task_list
        ]
        for future in as_completed(futures):
            results.append(future.result())
    return results
