"""AdAgentFlow-RT full contractual runtime baseline.

Contract monitor + fault localizer + bounded recovery + event-sourced trace +
artifact invalidation. This is the proposed method. The shared core wires up
ablations (``without_contract_monitor``, ``without_fault_localizer``,
``without_bounded_recovery``, ``without_event_trace``) by toggling internal
flags without code branching here.
"""
from __future__ import annotations

from experiments.harness.runtime_adapters._core import evaluate_task
from experiments.harness.runtime_adapters.base import RuntimeAdapter


class AdAgentFlowRTAdapter(RuntimeAdapter):
    method_name = "adagentflow_rt"

    def run_task(self, task, context, stressors, runtime_config):
        return evaluate_task(
            task=task,
            method=self.method_name,
            seed=hash((task.task_id, self.method_name)) & 0xFFFFFFFF,
            stressors=stressors,
            runtime_config=runtime_config,
        )
