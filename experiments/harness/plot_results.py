"""Generate paper figure artifacts from aggregated experiment summaries.

This module intentionally avoids optional plotting dependencies. It writes
machine-readable CSV data for each planned figure and simple valid PDF pages
containing the data values. The PDFs are placeholders visually, but no longer
empty placeholders: each is backed by the current summary metrics.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


FIGURES = {
    "system_architecture.pdf": "Figure 1: AdAgentFlow-RT contractual runtime architecture",
    "stress_harness.pdf": "Figure 2: Production-stress evaluation harness",
    "success_vs_concurrency.pdf": "Figure 3: Success rate vs concurrency",
    "latency_vs_concurrency.pdf": "Figure 4: P95 latency vs concurrency",
    "recovery_vs_fault_rate.pdf": "Figure 5: Recovery and dead-letter rate vs fault rate",
    "cost_per_success.pdf": "Figure 6: Cost per successful task under fault injection",
    "agentchange_recovery.pdf": "Figure 7: AgentChangeBench GSRT and TCRR comparison",
    "ablation_study.pdf": "Figure 8: Ablation study",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="append", default=[])
    parser.add_argument("--fig-dir", default="paper/aamas2026/figs")
    parser.add_argument("--plot-dir", default="experiments/results/plots")
    args = parser.parse_args()

    rows = load_summaries(args.summary) if args.summary else []
    figure_rows = build_figure_rows(rows)
    for directory in (Path(args.fig_dir), Path(args.plot_dir)):
        directory.mkdir(parents=True, exist_ok=True)
        write_figures(directory, figure_rows)
    write_ablation_table(Path("paper/aamas2026/tables/ablation_table.csv"), rows)


def load_summaries(paths: Iterable[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        rows.extend(data if isinstance(data, list) else [data])
    return rows


def build_figure_rows(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    return {
        "system_architecture": [
            {"component": name, "role": role}
            for name, role in [
                ("Contract Registry", "load contracts"),
                ("Execution Graph", "schedule dependencies"),
                ("Runtime Monitor", "detect violations"),
                ("Fault Localizer", "classify and contain faults"),
                ("Recovery Controller", "select bounded recovery"),
                ("Event Log", "trace and replay"),
                ("Stress Harness", "evaluate reliability"),
            ]
        ],
        "stress_harness": [
            {"stage": idx, "name": name}
            for idx, name in enumerate(
                [
                    "benchmark task",
                    "runtime adapter",
                    "stress layer",
                    "runtime strategy",
                    "benchmark environment",
                    "benchmark + runtime evaluator",
                ],
                start=1,
            )
        ],
        "success_vs_concurrency": _metric_rows(rows, "task_success_rate"),
        "latency_vs_concurrency": _metric_rows(rows, "p95_latency_ms"),
        "recovery_vs_fault_rate": _combined_metric_rows(rows, ["recovery_success_rate", "dead_letter_rate"]),
        "cost_per_success": _metric_rows(rows, "cost_per_successful_task"),
        "agentchange_recovery": _combined_metric_rows(rows, ["GSRT", "TCRR", "recovery_success_rate"], benchmark="agentchange"),
        "ablation_study": _ablation_rows(rows),
    }


def write_figures(directory: Path, figure_rows: Dict[str, List[Dict[str, Any]]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for pdf_name, title in FIGURES.items():
        stem = pdf_name.removesuffix(".pdf")
        rows = figure_rows.get(stem, [])
        csv_path = directory / f"{stem}.csv"
        write_csv(csv_path, rows)
        write_minimal_pdf(directory / pdf_name, title, rows)


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row}) or ["note"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        if rows:
            writer.writerows(rows)
        else:
            writer.writerow({"note": "no data"})


def write_ablation_table(path: Path, rows: List[Dict[str, Any]]) -> None:
    table_rows = _ablation_rows(rows)
    fields = [
        "method",
        "ablation",
        "task_success_rate",
        "dead_letter_rate",
        "recovery_success_rate",
        "silent_failure_rate",
        "mean_time_to_recover_ms",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in table_rows:
            writer.writerow({field: row.get(field) for field in fields})


def _metric_rows(rows: List[Dict[str, Any]], metric: str) -> List[Dict[str, Any]]:
    return [
        {
            "benchmark": row.get("benchmark"),
            "domain": row.get("domain"),
            "method": row.get("method"),
            "ablation": row.get("ablation"),
            "concurrency": row.get("max_concurrency", "smoke"),
            "fault_rate": row.get("fault_rate", "mixed"),
            "metric": metric,
            "value": row.get(metric),
        }
        for row in rows
        if row.get(metric) is not None
    ]


def _combined_metric_rows(rows: List[Dict[str, Any]], metrics: List[str], benchmark: str | None = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        if benchmark and row.get("benchmark") != benchmark:
            continue
        for metric in metrics:
            if row.get(metric) is None:
                continue
            out.append(
                {
                    "benchmark": row.get("benchmark"),
                    "domain": row.get("domain"),
                    "method": row.get("method"),
                    "ablation": row.get("ablation"),
                    "metric": metric,
                    "value": row.get(metric),
                }
            )
    return out


def _ablation_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        row
        for row in rows
        if row.get("method") in {"adagentflow_rt", "retry_only"} and (
            row.get("ablation") is not None or row.get("method") == "retry_only"
        )
    ]


def write_minimal_pdf(path: Path, title: str, rows: List[Dict[str, Any]]) -> None:
    lines = [title]
    for row in rows[:12]:
        compact = ", ".join(f"{k}={v}" for k, v in row.items() if v is not None)
        lines.append(compact[:92])
    if len(rows) > 12:
        lines.append(f"... {len(rows) - 12} more rows")
    stream = "\n".join(
        f"BT /F1 9 Tf 48 {740 - idx * 18} Td ({_pdf_escape(line)}) Tj ET"
        for idx, line in enumerate(lines[:36])
    )
    write_pdf(path, stream)


def write_pdf(path: Path, stream: str) -> None:
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream.encode('utf-8'))} >>\nstream\n{stream}\nendstream",
    ]
    chunks = ["%PDF-1.4\n"]
    offsets = [0]
    current = len(chunks[0].encode("utf-8"))
    for idx, obj in enumerate(objects, start=1):
        offsets.append(current)
        chunk = f"{idx} 0 obj\n{obj}\nendobj\n"
        chunks.append(chunk)
        current += len(chunk.encode("utf-8"))
    xref_offset = current
    xref_lines = ["xref\n", "0 6\n", "0000000000 65535 f \n"]
    xref_lines.extend(f"{offset:010d} 00000 n \n" for offset in offsets[1:])
    trailer = f"trailer\n<< /Root 1 0 R /Size 6 >>\nstartxref\n{xref_offset}\n%%EOF\n"
    path.write_text("".join(chunks + xref_lines + [trailer]), encoding="utf-8")


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


if __name__ == "__main__":
    main()
