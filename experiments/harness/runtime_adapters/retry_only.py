"""Retry-only baseline.

Bounded retries on transport / json failure. No schema validation, no fault
localization, no recovery policy. The paper uses it to show that retries alone
amplify cost without identifying the contaminated artifact.
"""
from __future__ import annotations

from experiments.harness.runtime_adapters._core import evaluate_task
from experiments.harness.runtime_adapters.base import RuntimeAdapter


class RetryOnlyAdapter(RuntimeAdapter):
    method_name = "retry_only"

    def run_task(self, task, context, stressors, runtime_config):
        return evaluate_task(
            task=task,
            method=self.method_name,
            seed=hash((task.task_id, self.method_name)) & 0xFFFFFFFF,
            stressors=stressors,
            runtime_config=runtime_config,
        )
