"""Partial response stressor."""
from __future__ import annotations

from experiments.harness.stressors.base import InjectedFault, Stressor


class PartialResponseStressor(Stressor):
    name = "partial_response"

    def apply(self, call):
        if "content" in call and isinstance(call["content"], str):
            call["content"] = call["content"][: max(1, len(call["content"]) // 2)]
        elif "resolution" in call:
            call["resolution"] = str(call["resolution"])[:1]
        return InjectedFault(self.name, "truncated response", {"keys": sorted(call)}).__dict__.copy()
