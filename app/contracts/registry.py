"""In-memory contract registry with JSON loading support."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from app.contracts.models import Contract, ResourceBudget


class ContractRegistry:
    def __init__(self, contracts: Optional[Iterable[Contract]] = None):
        self._contracts: Dict[str, Contract] = {}
        for contract in contracts or []:
            self.register(contract)

    def register(self, contract: Contract) -> None:
        if not contract.name:
            raise ValueError("contract.name is required")
        self._contracts[contract.name] = contract

    def get(self, name: str) -> Contract:
        try:
            return self._contracts[name]
        except KeyError as exc:
            raise KeyError(f"unknown contract: {name}") from exc

    def maybe_get(self, name: str) -> Optional[Contract]:
        return self._contracts.get(name)

    def names(self) -> list[str]:
        return sorted(self._contracts)

    @classmethod
    def from_dicts(cls, items: Iterable[Dict[str, Any]]) -> "ContractRegistry":
        registry = cls()
        for item in items:
            registry.register(contract_from_dict(item))
        return registry

    @classmethod
    def from_json_file(cls, path: str | Path) -> "ContractRegistry":
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        items = data.get("contracts", data if isinstance(data, list) else [data])
        return cls.from_dicts(items)


def contract_from_dict(data: Dict[str, Any]) -> Contract:
    budget_data = data.get("resource_budget") or {}
    return Contract(
        name=data["name"],
        capability=data["capability"],
        input_schema=data.get("input_schema"),
        output_schema=data.get("output_schema"),
        preconditions=list(data.get("preconditions") or []),
        postconditions=list(data.get("postconditions") or []),
        semantic_checks=list(data.get("semantic_checks") or []),
        resource_budget=ResourceBudget(**budget_data),
        recovery_policy=dict(data.get("recovery_policy") or {}),
        escalation_policy=dict(data.get("escalation_policy") or {}),
    )
