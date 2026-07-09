"""Refresh paper-facing tables and figures from aggregated summaries."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, Iterable, List

from experiments.harness.export_paper_tables import (
    AGENTCHANGE_FIELDS,
    MAIN_FIELDS,
    RUNTIME_FIELDS,
    load_summaries,
    write_failure_breakdown,
    write_table,
)
from experiments.harness.plot_results import build_figure_rows, write_ablation_table, write_figures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="append", required=True)
    parser.add_argument("--table-dir", default="paper/aamas2026/tables")
    parser.add_argument("--fig-dir", default="paper/aamas2026/figs")
    parser.add_argument("--plot-dir", default="experiments/results/plots")
    args = parser.parse_args()

    refresh_paper_artifacts(
        summary_paths=args.summary,
        table_dir=Path(args.table_dir),
        fig_dir=Path(args.fig_dir),
        plot_dir=Path(args.plot_dir),
    )


def refresh_paper_artifacts(
    *,
    summary_paths: Iterable[str],
    table_dir: Path,
    fig_dir: Path,
    plot_dir: Path,
) -> List[Path]:
    rows = load_summaries(summary_paths)
    written: List[Path] = []
    written.extend(write_paper_tables(table_dir, rows))
    figure_rows = build_figure_rows(rows)
    for directory in (fig_dir, plot_dir):
        write_figures(directory, figure_rows)
        written.extend(_expected_figure_paths(directory))
    ablation_table = table_dir / "ablation_table.csv"
    write_ablation_table(ablation_table, rows)
    written.append(ablation_table)
    return written


def write_paper_tables(table_dir: Path, rows: List[Dict[str, Any]]) -> List[Path]:
    table_dir.mkdir(parents=True, exist_ok=True)
    outputs = [
        table_dir / "main_tau3_results.csv",
        table_dir / "runtime_stability_metrics.csv",
        table_dir / "agentchange_recovery_metrics.csv",
        table_dir / "failure_recovery_breakdown.csv",
    ]
    write_table(outputs[0], [row for row in rows if row.get("benchmark") in {"tau3", "mock"}], MAIN_FIELDS)
    write_table(outputs[1], rows, RUNTIME_FIELDS)
    write_table(outputs[2], [row for row in rows if row.get("benchmark") == "agentchange"], AGENTCHANGE_FIELDS)
    write_failure_breakdown(outputs[3], rows)
    return outputs


def _expected_figure_paths(directory: Path) -> List[Path]:
    return sorted(list(directory.glob("*.csv")) + list(directory.glob("*.pdf")))


if __name__ == "__main__":
    main()
