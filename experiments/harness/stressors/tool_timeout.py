"""Tool timeout stressor."""
from __future__ import annotations

from experiments.harness.stressors.base import InjectedFault, Stressor


class ToolTimeoutStressor(Stressor):
    name = "tool_timeout"

    def apply(self, call):
        call["ok"] = False
        call["error"] = "timeout"
        return InjectedFault(self.name, "simulated tool timeout", {"error": "timeout"}).__dict__.copy()
