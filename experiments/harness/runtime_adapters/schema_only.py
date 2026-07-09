"""Schema-only runtime baseline."""
from __future__ import annotations

from uuid import uuid4

from app.contracts.models import Contract
from app.contracts.validators import validate_schema
from experiments.harness.runtime_adapters.base import RuntimeAdapter, RuntimeResult


class SchemaOnlyAdapter(RuntimeAdapter):
    method_name = "schema_only"

    def run_task(self, task, context, stressors, runtime_config):
        run_id = f"run_{uuid4().hex}"
        output = {"resolution": "ok", "policy_compliant": True}
        faults = []
        for stressor in stressors:
            event = {"task_id": task.task_id, "method": self.method_name, "phase": "schema"}
            if stressor.should_inject(event):
                faults.append(stressor.apply(output))
        contract = Contract(
            name="schema_only.default",
            capability="mock_resolution",
            output_schema={
                "type": "object",
                "required": ["resolution", "policy_compliant"],
                "properties": {
                    "resolution": {"type": "string"},
                    "policy_compliant": {"type": "boolean"},
                },
            },
        )
        violations = validate_schema(
            task_id=task.task_id,
            node_id="schema_node",
            contract=contract,
            payload=output,
        )
        recovered = bool(violations and runtime_config.get("repair_schema", True))
        success = not violations or recovered
        return RuntimeResult(
            benchmark=task.benchmark,
            domain=task.domain,
            task_id=task.task_id,
            trial_id=task.trial_id,
            method=self.method_name,
            run_id=run_id,
            success=success,
            native_metrics={"task_success": success, **task.native_metrics},
            runtime_metrics={
                "contract_violations": len(violations),
                "recovery_actions": 1 if recovered else 0,
            },
            latency_ms=1300 if recovered else 1000,
            tool_calls=2,
            llm_calls=1 + (1 if recovered else 0),
            attempts=1 + (1 if recovered else 0),
            injected_faults=faults,
            recovered=recovered,
            dead_letter=not success,
            error=None if success else "schema violation",
        )
