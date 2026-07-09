"""Retry-only baseline."""
from __future__ import annotations

from uuid import uuid4

from experiments.harness.runtime_adapters.base import RuntimeAdapter, RuntimeResult


class RetryOnlyAdapter(RuntimeAdapter):
    method_name = "retry_only"

    def run_task(self, task, context, stressors, runtime_config):
        run_id = f"run_{uuid4().hex}"
        max_retries = int(runtime_config.get("max_retries", 2))
        faults = []
        attempts = 1
        success = True
        for stressor in stressors:
            event = {"task_id": task.task_id, "method": self.method_name, "phase": "attempt"}
            if stressor.should_inject(event):
                faults.append(stressor.apply({"ok": True, "content": "tool response"}))
                attempts += 1
                success = attempts <= max_retries + 1
        return RuntimeResult(
            benchmark=task.benchmark,
            domain=task.domain,
            task_id=task.task_id,
            trial_id=task.trial_id,
            method=self.method_name,
            run_id=run_id,
            success=success,
            ablation=runtime_config.get("ablation"),
            benchmark_adapter_mode=task.adapter_mode,
            external_command=task.external_command,
            native_metrics={**task.native_metrics, "task_success": success},
            runtime_metrics={"contract_violations": 0, "recovery_actions": max(0, attempts - 1)},
            latency_ms=1000 * attempts,
            tool_calls=2 * attempts,
            llm_calls=attempts,
            attempts=attempts,
            injected_faults=faults,
            recovered=bool(faults and success),
            dead_letter=not success,
            error=None if success else "retry budget exhausted",
        )
