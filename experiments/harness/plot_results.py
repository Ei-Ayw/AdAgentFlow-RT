"""Generate placeholder plot artifacts from aggregated results.

The script avoids optional plotting dependencies in the skeleton. It writes
valid minimal PDF placeholders and an ablation CSV so paper paths exist.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path


PLOTS = [
    "success_vs_concurrency.pdf",
    "latency_vs_concurrency.pdf",
    "recovery_vs_fault_rate.pdf",
    "cost_per_success.pdf",
    "agentchange_recovery.pdf",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fig-dir", default="paper/aamas2026/figs")
    parser.add_argument("--plot-dir", default="experiments/results/plots")
    args = parser.parse_args()
    for directory in (Path(args.fig_dir), Path(args.plot_dir)):
        directory.mkdir(parents=True, exist_ok=True)
        for plot in PLOTS:
            write_minimal_pdf(directory / plot, plot)
    table_path = Path("paper/aamas2026/tables/ablation_table.csv")
    table_path.parent.mkdir(parents=True, exist_ok=True)
    with table_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["method", "success_rate", "dead_letter_rate", "recovery_success_rate"])
        writer.writerow(["adagentflow_rt", "TBD", "TBD", "TBD"])


def write_minimal_pdf(path: Path, title: str) -> None:
    content = f"Placeholder for {title}"
    stream = f"BT /F1 12 Tf 72 720 Td ({content}) Tj ET"
    pdf = (
        "%PDF-1.4\n"
        "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        "2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        "3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n"
        "4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
        f"5 0 obj << /Length {len(stream)} >> stream\n{stream}\nendstream endobj\n"
        "xref\n0 6\n0000000000 65535 f \n"
        "trailer << /Root 1 0 R /Size 6 >>\nstartxref\n0\n%%EOF\n"
    )
    path.write_text(pdf, encoding="utf-8")


if __name__ == "__main__":
    main()
