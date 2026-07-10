"""Normalize external benchmark outputs into harness JSONL rows."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from experiments.harness.runtime_adapters.base import RuntimeResult


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--benchmark", required=True, choices=["tau3", "agentchange"])
    parser.add_argument("--domain", required=True)
    parser.add_argument("--method", default="external_native")
    parser.add_argument("--suite-run", default=None)
    parser.add_argument("--fault-rate", type=float, default=None)
    parser.add_argument("--max-concurrency", type=int, default=None)
    parser.add_argument("--stress", default=None)
    parser.add_argument("--ablation", default=None)
    args = parser.parse_args()

    rows = import_external_results(
        input_path=Path(args.input),
        benchmark=args.benchmark,
        domain=args.domain,
        method=args.method,
        suite_run=args.suite_run,
        fault_rate=args.fault_rate,
        max_concurrency=args.max_concurrency,
        stress=args.stress,
        ablation=args.ablation,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")


def import_external_results(
    *,
    input_path: Path,
    benchmark: str,
    domain: str,
    method: str,
    suite_run: str | None = None,
    fault_rate: float | None = None,
    max_concurrency: int | None = None,
    stress: str | None = None,
    ablation: str | None = None,
) -> List[RuntimeResult]:
    return [
        normalize_external_row(
            row,
            benchmark=benchmark,
            domain=domain,
            method=method,
            suite_run=suite_run,
            fault_rate=fault_rate,
            max_concurrency=max_concurrency,
            stress=stress,
            ablation=ablation,
        )
        for row in load_external_rows(input_path)
    ]


def load_external_rows(path: Path) -> List[Dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        rows = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rows.append(json.loads(line))
        return rows

    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [_ensure_dict(row) for row in payload]
    if isinstance(payload, dict):
        for key in ("results", "episodes", "tasks", "rows"):
            if isinstance(payload.get(key), list):
                return [_ensure_dict(row) for row in payload[key]]
        return [payload]
    raise ValueError(f"unsupported external result payload in {path}")


def normalize_external_row(
    row: Dict[str, Any],
    *,
    benchmark: str,
    domain: str,
    method: str,
    suite_run: str | None = None,
    fault_rate: float | None = None,
    max_concurrency: int | None = None,
    stress: str | None = None,
    ablation: str | None = None,
) -> RuntimeResult:
    task_id = str(_first_present(row, ["task_id", "id", "example_id", "episode_id"], "unknown_task"))
    trial_id = int(_first_present(row, ["trial_id", "trial", "seed"], 0) or 0)
    success = bool(_first_present(row, ["success", "task_success", "passed", "pass"], False))
    native_metrics = _native_metrics(row)
    native_metrics.setdefault("task_success", success)

    return RuntimeResult(
        benchmark=str(row.get("benchmark", benchmark)),
        domain=str(row.get("domain", domain)),
        task_id=task_id,
        trial_id=trial_id,
        method=str(row.get("method", method)),
        run_id=str(row.get("run_id") or f"external_{benchmark}_{domain}_{task_id}_{trial_id}"),
        success=success,
        suite_run=_optional_str(row.get("suite_run", suite_run)),
        fault_rate=_optional_float(row.get("fault_rate", fault_rate)),
        max_concurrency=_optional_int(row.get("max_concurrency", max_concurrency)),
        stress=_optional_str(row.get("stress", stress)),
        ablation=_optional_str(row.get("ablation", ablation)),
        benchmark_adapter_mode="external",
        external_command=_string_list(row.get("external_command", [])),
        native_metrics=native_metrics,
        runtime_metrics=_dict_or_empty(row.get("runtime_metrics")),
        events=list(_iter_dicts(row.get("events", []))),
        trajectory_path=_optional_str(_first_present(row, ["trajectory_path", "trajectory", "log_path"], None)),
        runtime_trace_path=_optional_str(row.get("runtime_trace_path")),
        latency_ms=int(_first_present(row, ["latency_ms", "duration_ms", "elapsed_ms"], 0) or 0),
        tool_calls=int(_first_present(row, ["tool_calls", "num_tool_calls", "actions"], 0) or 0),
        llm_calls=int(_first_present(row, ["llm_calls", "num_llm_calls", "model_calls"], 0) or 0),
        attempts=int(_first_present(row, ["attempts", "num_attempts"], 1) or 1),
        injected_faults=list(_iter_dicts(row.get("injected_faults", []))),
        recovered=bool(row.get("recovered", False)),
        dead_letter=bool(row.get("dead_letter", False)),
        error=_optional_str(row.get("error")),
    )


def _native_metrics(row: Dict[str, Any]) -> Dict[str, Any]:
    metrics = {}
    for key in ("native_metrics", "metrics", "scores"):
        if isinstance(row.get(key), dict):
            metrics.update(row[key])
    for key in ("TSR", "TUE", "TCRR", "GSRT", "policy_compliance", "task_success"):
        if key in row:
            metrics[key] = row[key]
    return metrics


def _first_present(row: Dict[str, Any], keys: Iterable[str], default: Any) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return default


def _ensure_dict(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"external result row must be an object, got {type(value).__name__}")
    return value


def _dict_or_empty(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _iter_dicts(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                yield item


def _string_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return value.split()
    return []


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


if __name__ == "__main__":
    main()
