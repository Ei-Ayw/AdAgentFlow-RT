"""Repeated-trial helpers."""
from __future__ import annotations

from dataclasses import replace
from typing import Iterable, List

from experiments.harness.benchmark_adapters.base import BenchmarkTask


def repeat_tasks(tasks: Iterable[BenchmarkTask], num_trials: int) -> List[BenchmarkTask]:
    repeated: List[BenchmarkTask] = []
    for trial_id in range(num_trials):
        for task in tasks:
            repeated.append(replace(task, trial_id=trial_id))
    return repeated
