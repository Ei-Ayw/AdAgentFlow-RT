"""Finalize a completed suite into summaries, paper tables, and figures."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List

from experiments.harness.aggregate_suite import summarize_suite
from experiments.harness.refresh_paper_artifacts import refresh_paper_artifacts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite-dir", required=True)
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--summary-csv", default=None)
    parser.add_argument("--table-dir", default="paper/aamas2026/tables")
    parser.add_argument("--fig-dir", default="paper/aamas2026/figs")
    parser.add_argument("--plot-dir", default="experiments/results/plots")
    args = parser.parse_args()

    summary_json = Path(args.summary_json)
    summary_csv = Path(args.summary_csv) if args.summary_csv else summary_json.with_suffix(".csv")
    finalize_suite(
        suite_dir=Path(args.suite_dir),
        summary_json=summary_json,
        summary_csv=summary_csv,
        table_dir=Path(args.table_dir),
        fig_dir=Path(args.fig_dir),
        plot_dir=Path(args.plot_dir),
    )


def finalize_suite(
    *,
    suite_dir: Path,
    summary_json: Path,
    summary_csv: Path,
    table_dir: Path,
    fig_dir: Path,
    plot_dir: Path,
) -> Dict[str, Any]:
    summaries = summarize_suite(suite_dir)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summaries, indent=2, ensure_ascii=False), encoding="utf-8")
    write_summary_csv(summary_csv, summaries)
    written = refresh_paper_artifacts(
        summary_paths=[str(summary_json)],
        table_dir=table_dir,
        fig_dir=fig_dir,
        plot_dir=plot_dir,
    )
    return {
        "suite_dir": str(suite_dir),
        "summary_json": str(summary_json),
        "summary_csv": str(summary_csv),
        "summary_rows": len(summaries),
        "paper_artifacts": [str(path) for path in written],
    }


def write_summary_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row}) or ["note"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        if rows:
            writer.writerows(rows)
        else:
            writer.writerow({"note": "no result rows"})


if __name__ == "__main__":
    main()
