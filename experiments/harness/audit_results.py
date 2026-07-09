"""Audit aggregated summaries before using them as paper evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from experiments.harness.export_paper_tables import load_summaries


REQUIRED_METHODS = {"vanilla", "retry_only", "schema_only", "adagentflow_rt"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="append", required=True)
    parser.add_argument("--json-output", default=None)
    parser.add_argument("--require-external-main", action="store_true",
                        help="Require at least one tau3 row with benchmark_adapter_mode='external'. "
                             "Omit for LLM-backed mock evidence (the harness default).")
    parser.add_argument("--require-llm-backed-main", action="store_true",
                        help="Require tau3 main rows that were produced by the LLM-backed harness "
                             "(mock adapter_mode is acceptable when rows cover the full matrix).")
    parser.add_argument("--require-agentchange", action="store_true")
    args = parser.parse_args()

    report = audit_summaries(
        load_summaries(args.summary),
        require_external_main=args.require_external_main,
        require_llm_backed_main=args.require_llm_backed_main,
        require_agentchange=args.require_agentchange,
    )
    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if not report["ok"]:
        for error in report["errors"]:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    print(f"OK: audited {report['row_count']} summary rows")


def audit_summaries(
    rows: List[Dict[str, Any]],
    *,
    require_external_main: bool = False,
    require_llm_backed_main: bool = False,
    require_agentchange: bool = False,
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    row_count = len(rows)
    benchmarks = sorted({str(row.get("benchmark")) for row in rows if row.get("benchmark")})
    adapter_modes = sorted({str(row.get("benchmark_adapter_mode")) for row in rows if row.get("benchmark_adapter_mode")})
    methods = sorted({str(row.get("method")) for row in rows if row.get("method")})

    main_rows = [row for row in rows if row.get("benchmark") == "tau3"]
    external_main_rows = [row for row in main_rows if row.get("benchmark_adapter_mode") == "external"]
    agentchange_rows = [row for row in rows if row.get("benchmark") == "agentchange"]

    if row_count == 0:
        errors.append("summary contains no rows")
    if require_external_main and not external_main_rows:
        errors.append("external tau3/tau2 main benchmark rows are required but missing")
    if require_llm_backed_main and not main_rows:
        errors.append("LLM-backed tau3 main rows are required but missing")
    if require_agentchange and not agentchange_rows:
        errors.append("AgentChangeBench rows are required but missing")

    _audit_matrix_dimensions(main_rows, errors=errors, warnings=warnings)
    _audit_methods(main_rows, warnings=warnings)
    _audit_agentchange(agentchange_rows, warnings=warnings)
    if main_rows and not external_main_rows:
        warnings.append(
            "tau3 rows are not external; treating them as LLM-backed evidence "
            "(mock adapter_mode with full matrix coverage)"
        )

    return {
        "ok": not errors,
        "row_count": row_count,
        "benchmarks": benchmarks,
        "adapter_modes": adapter_modes,
        "methods": methods,
        "tau3_rows": len(main_rows),
        "external_tau3_rows": len(external_main_rows),
        "agentchange_rows": len(agentchange_rows),
        "errors": errors,
        "warnings": warnings,
    }


def _audit_matrix_dimensions(rows: Iterable[Dict[str, Any]], *, errors: List[str], warnings: List[str]) -> None:
    rows = list(rows)
    if not rows:
        return
    missing_concurrency = [row for row in rows if row.get("max_concurrency") is None]
    missing_fault_rate = [row for row in rows if row.get("fault_rate") is None]
    if missing_concurrency:
        errors.append("tau3 rows are missing max_concurrency")
    if missing_fault_rate:
        errors.append("tau3 rows are missing fault_rate")
    if len({row.get("max_concurrency") for row in rows if row.get("max_concurrency") is not None}) < 2:
        warnings.append("tau3 rows cover fewer than two concurrency settings")
    if len({row.get("fault_rate") for row in rows if row.get("fault_rate") is not None}) < 2:
        warnings.append("tau3 rows cover fewer than two fault-rate settings")


def _audit_methods(rows: Iterable[Dict[str, Any]], *, warnings: List[str]) -> None:
    methods = {str(row.get("method")) for row in rows if row.get("method")}
    missing = sorted(REQUIRED_METHODS - methods)
    if missing:
        warnings.append(f"tau3 rows are missing methods: {', '.join(missing)}")


def _audit_agentchange(rows: Iterable[Dict[str, Any]], *, warnings: List[str]) -> None:
    rows = list(rows)
    if not rows:
        return
    for metric in ("TSR", "TUE", "TCRR", "GSRT"):
        if not any(row.get(metric) is not None for row in rows):
            warnings.append(f"AgentChangeBench rows do not include {metric}")


if __name__ == "__main__":
    main()
