"""Worker crash stressor."""
from __future__ import annotations

from experiments.harness.stressors.base import InjectedFault, Stressor


class WorkerCrashStressor(Stressor):
    name = "worker_crash"

    def apply(self, call):
        call["ok"] = False
        call["error"] = "worker_crash"
        return InjectedFault(self.name, "simulated worker crash", {"error": "worker_crash"}).__dict__.copy()
