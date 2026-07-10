"""Fault stressor base classes."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class InjectedFault:
    stressor: str
    detail: str
    payload: Dict[str, Any] = field(default_factory=dict)


class Stressor:
    name = "base"

    def __init__(self, rate: float = 0.0, seed: int = 0):
        self.rate = float(rate)
        self.random = random.Random(seed)

    def should_inject(self, event: Dict[str, Any]) -> bool:
        return self.random.random() < self.rate

    def apply(self, call: Dict[str, Any]) -> Dict[str, Any]:
        return InjectedFault(self.name, "no-op").__dict__.copy()
