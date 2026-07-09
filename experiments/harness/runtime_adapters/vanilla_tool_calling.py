"""Vanilla tool-calling baseline."""
from __future__ import annotations

from uuid import uuid4

from experiments.harness.runtime_adapters.base import RuntimeAdapter, RuntimeResult


class VanillaToolCallingAdapter(RuntimeAdapter):
    method_name = "vanilla"

    def run_task(self, task, context, stressors, runtime_config):
        run_id = f"run_{uuid4().hex}"
        faults = []
        success = True
        for stressor in stressors:
            event = {"task_id": task.task_id, "method": self.method_name, "phase": "tool_call"}
            if stressor.should_inject(event):
                faults.append(stressor.apply({"ok": True, "content": "tool response"}))
                success = False
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
            runtime_metrics={"contract_violations": 0, "recovery_actions": 0},
            latency_ms=1000 + 100 * len(faults),
            tool_calls=2 + len(faults),
            llm_calls=1,
            attempts=1,
            injected_faults=faults,
            dead_letter=not success,
            error=None if success else "unhandled injected fault",
        )
