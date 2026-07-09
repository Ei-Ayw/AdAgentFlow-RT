"""Duplicate message stressor."""
from __future__ import annotations

from experiments.harness.stressors.base import InjectedFault, Stressor


class DuplicateMessageStressor(Stressor):
    name = "duplicate_message"

    def apply(self, call):
        call["duplicate_delivery"] = True
        return InjectedFault(self.name, "duplicated runtime node delivery", {"duplicate": True}).__dict__.copy()
