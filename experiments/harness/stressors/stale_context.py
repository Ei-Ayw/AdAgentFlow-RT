"""Stale context stressor."""
from __future__ import annotations

from experiments.harness.stressors.base import InjectedFault, Stressor


class StaleContextStressor(Stressor):
    name = "stale_context"

    def apply(self, call):
        call["context_version"] = "stale"
        return InjectedFault(self.name, "served stale context", {"context_version": "stale"}).__dict__.copy()
