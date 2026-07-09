"""Vanilla tool-calling baseline.

No contracts, no recovery, no schema validation, no fault localizer.
This is the lower-bound baseline. The paper uses it to expose silent failures.
"""
from __future__ import annotations

from experiments.harness.runtime_adapters._core import evaluate_task
from experiments.harness.runtime_adapters.base import RuntimeAdapter


class VanillaToolCallingAdapter(RuntimeAdapter):
    method_name = "vanilla"

    def run_task(self, task, context, stressors, runtime_config):
        return evaluate_task(
            task=task,
            method=self.method_name,
            seed=hash((task.task_id, self.method_name)) & 0xFFFFFFFF,
            stressors=stressors,
            runtime_config=runtime_config,
        )
