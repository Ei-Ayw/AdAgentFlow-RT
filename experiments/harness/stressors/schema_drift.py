"""Schema drift stressor."""
from __future__ import annotations

from experiments.harness.stressors.base import InjectedFault, Stressor


class SchemaDriftStressor(Stressor):
    name = "schema_drift"

    def apply(self, call):
        if "policy_compliant" in call:
            call["policyCompliant"] = call.pop("policy_compliant")
        elif call:
            key = next(iter(call))
            call[f"drifted_{key}"] = call.pop(key)
        return InjectedFault(self.name, "renamed or removed schema field", {"keys": sorted(call)}).__dict__.copy()
