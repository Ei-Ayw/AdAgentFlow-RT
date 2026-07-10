"""Schema-only baseline.

JSON-schema validation plus quick repair. No semantic contracts, no graph-level
fault localization. The paper uses it to show that schema enforcement catches
some drift but not semantic violations.
"""
from __future__ import annotations

from experiments.harness.runtime_adapters._core import evaluate_task
from experiments.harness.runtime_adapters.base import RuntimeAdapter, stable_task_seed


class SchemaOnlyAdapter(RuntimeAdapter):
    method_name = "schema_only"

    def run_task(self, task, context, stressors, runtime_config):
        return evaluate_task(
            task=task,
            method=self.method_name,
            seed=stable_task_seed(task.task_id, self.method_name),
            context=context,
            stressors=stressors,
            runtime_config=runtime_config,
        )
