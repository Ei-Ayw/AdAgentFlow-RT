"""Rate-limit stressor."""
from __future__ import annotations

from experiments.harness.stressors.base import InjectedFault, Stressor


class RateLimitStressor(Stressor):
    name = "rate_limit"

    def apply(self, call):
        call["ok"] = False
        call["error"] = "rate_limit"
        return InjectedFault(self.name, "simulated rate limit", {"error": "rate_limit"}).__dict__.copy()
