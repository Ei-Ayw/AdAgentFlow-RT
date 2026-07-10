"""Dependency-light config parsing for experiment YAML-like files."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


def load_simple_config(path: str | Path) -> Dict[str, Any]:
    """Load the small YAML subset used by harness configs.

    Supported syntax:
    - `key: value`
    - `key: [a, b, c]`
    - comments and blank lines
    """
    config: Dict[str, Any] = {}
    with open(path, "r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            if ":" not in line:
                raise ValueError(f"unsupported config line in {path}: {raw_line.rstrip()}")
            key, raw_value = line.split(":", 1)
            config[key.strip()] = parse_value(raw_value.strip())
    return config


def parse_value(raw: str) -> Any:
    if raw == "":
        return None
    if raw.startswith("[") and raw.endswith("]"):
        body = raw[1:-1].strip()
        if not body:
            return []
        return [parse_value(part.strip()) for part in body.split(",")]
    lowered = raw.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"none", "null"}:
        return None
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        return raw.strip("\"'")


def config_methods(config: Dict[str, Any]) -> list[str]:
    methods = config.get("methods", ["vanilla", "retry_only", "schema_only", "adagentflow_rt"])
    if isinstance(methods, str):
        return [part.strip() for part in methods.split(",") if part.strip()]
    return [str(method) for method in methods]


def config_stressors(config: Dict[str, Any]) -> list[str]:
    stressors = config.get("stressors") or config.get("stress") or []
    if stressors == "none":
        return []
    if isinstance(stressors, str):
        return [part.strip() for part in stressors.split(",") if part.strip()]
    return [str(stressor) for stressor in stressors]


def config_list(config: Dict[str, Any], key: str, default: list[Any] | None = None) -> list[Any]:
    value = config.get(key, default or [])
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [value]
