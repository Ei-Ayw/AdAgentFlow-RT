"""Generate paper figures from aggregated experiment summaries.

Each figure is emitted as both machine-readable CSV and a publication-facing
PDF. Matplotlib is used when available; a small text-PDF fallback keeps the
artifact pipeline usable in minimal environments.
"""
from __future__ import annotations

import argparse
import csv
import json
import textwrap
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List


FIGURES = {
    "system_architecture.pdf": "AdAgentFlow-RT contractual runtime architecture",
    "stress_harness.pdf": "Production-stress evaluation harness",
    "success_vs_concurrency.pdf": "Success rate vs concurrency",
    "latency_vs_concurrency.pdf": "P95 latency vs concurrency",
    "recovery_vs_fault_rate.pdf": "Recovery and dead-letter rate vs fault rate",
    "cost_per_success.pdf": "Cost per successful task under fault injection",
    "agentchange_recovery.pdf": "AgentChangeBench GSRT and TCRR comparison",
    "ablation_study.pdf": "Ablation study",
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
        write_figure_pdf(directory / pdf_name, stem, title, rows)


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


def write_figure_pdf(path: Path, stem: str, title: str, rows: List[Dict[str, Any]]) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        write_minimal_pdf(path, title, rows)
        return

    plotters: Dict[str, Callable[[Any, List[Dict[str, Any]], str], None]] = {
        "system_architecture": _plot_architecture,
        "stress_harness": _plot_pipeline,
        "success_vs_concurrency": lambda ax, data, heading: _plot_metric_by_concurrency(
            ax, data, heading, ylabel="Task success rate", ylim=(0, 1)
        ),
        "latency_vs_concurrency": lambda ax, data, heading: _plot_metric_by_concurrency(
            ax, data, heading, ylabel="P95 latency (ms)", ylim=None
        ),
        "recovery_vs_fault_rate": _plot_recovery_vs_fault,
        "cost_per_success": lambda ax, data, heading: _plot_metric_bars(
            ax, data, heading, ylabel="Cost per successful task"
        ),
        "agentchange_recovery": _plot_agentchange,
        "ablation_study": _plot_ablation,
    }
    plotter = plotters.get(stem, _plot_table_summary)
    fig, ax = plt.subplots(figsize=(7.2, 4.2), constrained_layout=True)
    plotter(ax, rows, title)
    fig.savefig(path, format="pdf")
    plt.close(fig)


def _plot_architecture(ax: Any, rows: List[Dict[str, Any]], title: str) -> None:
    from matplotlib.patches import FancyBboxPatch

    ax.set_title(title, fontsize=11, weight="bold")
    ax.set_axis_off()
    palette = ["#2f5597", "#6aa84f", "#bf9000", "#a64d79", "#45818e", "#cc4125", "#674ea7"]
    positions = [
        (0.08, 0.68),
        (0.31, 0.68),
        (0.54, 0.68),
        (0.77, 0.68),
        (0.18, 0.38),
        (0.43, 0.38),
        (0.68, 0.38),
    ]
    for idx, row in enumerate(rows):
        x, y = positions[idx]
        color = palette[idx % len(palette)]
        ax.add_patch(
            FancyBboxPatch(
                (x, y),
                0.16,
                0.18,
                boxstyle="round,pad=0.018,rounding_size=0.015",
                linewidth=1.0,
                edgecolor=color,
                facecolor=_lighten(color),
            )
        )
        ax.text(
            x + 0.08,
            y + 0.11,
            textwrap.fill(str(row["component"]), 16),
            ha="center",
            va="center",
            fontsize=7.2,
            weight="bold",
            linespacing=1.05,
        )
        ax.text(
            x + 0.08,
            y + 0.045,
            textwrap.fill(str(row["role"]), 20),
            ha="center",
            va="center",
            fontsize=6.4,
            color="#333333",
            linespacing=1.05,
        )
    ax.text(0.5, 0.61, "contracted execution", ha="center", fontsize=8, color="#555555")
    ax.text(0.5, 0.31, "recovery, tracing, and stress evaluation", ha="center", fontsize=8, color="#555555")
    ax.text(0.5, 0.16, "Contract checks, recovery decisions, and event-sourced traces bound runtime failures.", ha="center", fontsize=9)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)


def _plot_pipeline(ax: Any, rows: List[Dict[str, Any]], title: str) -> None:
    from matplotlib.patches import Rectangle

    ax.set_title(title, fontsize=11, weight="bold")
    ax.set_axis_off()
    colors = ["#d9ead3", "#cfe2f3", "#fff2cc", "#ead1dc", "#d0e0e3", "#f4cccc"]
    positions = [(0.08, 0.62), (0.39, 0.62), (0.70, 0.62), (0.08, 0.36), (0.39, 0.36), (0.70, 0.36)]
    for idx, row in enumerate(rows):
        x, y = positions[idx]
        ax.add_patch(
            Rectangle((x, y), 0.20, 0.17, linewidth=1, edgecolor="#444444", facecolor=colors[idx % len(colors)])
        )
        ax.text(
            x + 0.10,
            y + 0.105,
            textwrap.fill(str(row["name"]).title(), 18),
            ha="center",
            va="center",
            fontsize=7.2,
            linespacing=1.05,
        )
        ax.text(x + 0.10, y + 0.045, f"Stage {row['stage']}", ha="center", va="center", fontsize=6.5, color="#555555")
    ax.text(0.5, 0.22, "Public task data remains unchanged; production stress and runtime metrics are layered around it.", ha="center", fontsize=9)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)


def _plot_metric_by_concurrency(ax: Any, rows: List[Dict[str, Any]], title: str, *, ylabel: str, ylim: tuple[float, float] | None) -> None:
    grouped: Dict[str, Dict[float, List[float]]] = {}
    for row in rows:
        method = _method_label(row.get("method"))
        x = _as_float(row.get("concurrency"))
        value = _as_float(row.get("value"))
        if x is None or value is None:
            continue
        grouped.setdefault(method, {}).setdefault(x, []).append(value)
    for method, by_x in sorted(grouped.items()):
        xs = sorted(by_x)
        ys = [_mean(by_x[x]) for x in xs]
        ax.plot(xs, ys, marker="o", linewidth=1.8, label=method)
    _finish_axes(ax, title, "Concurrency", ylabel, ylim=ylim)


def _plot_recovery_vs_fault(ax: Any, rows: List[Dict[str, Any]], title: str) -> None:
    grouped: Dict[tuple[str, str], List[float]] = {}
    for row in rows:
        method = _method_label(row.get("method"))
        metric = str(row.get("metric"))
        value = _as_float(row.get("value"))
        if value is not None:
            grouped.setdefault((method, metric), []).append(value)
    labels = sorted({_method for _method, _metric in grouped})
    metrics = ["recovery_success_rate", "dead_letter_rate"]
    _grouped_bar(ax, labels, metrics, lambda label, metric: _mean(grouped.get((label, metric), [])))
    _finish_axes(ax, title, "Runtime strategy", "Rate", ylim=(0, 1))


def _plot_metric_bars(ax: Any, rows: List[Dict[str, Any]], title: str, *, ylabel: str) -> None:
    grouped: Dict[str, List[float]] = {}
    for row in rows:
        value = _as_float(row.get("value"))
        if value is not None and value > 0:
            grouped.setdefault(_method_label(row.get("method")), []).append(value)
    labels = sorted(grouped)
    ax.bar(labels, [_mean(grouped[label]) for label in labels], color="#4f81bd")
    _finish_axes(ax, title, "Runtime strategy", ylabel)


def _plot_agentchange(ax: Any, rows: List[Dict[str, Any]], title: str) -> None:
    grouped: Dict[tuple[str, str], List[float]] = {}
    for row in rows:
        method = _method_label(row.get("method"))
        metric = str(row.get("metric"))
        value = _as_float(row.get("value"))
        if value is not None:
            grouped.setdefault((method, metric), []).append(value)
    labels = sorted({_method for _method, _metric in grouped})
    metrics = ["GSRT", "TCRR", "recovery_success_rate"]
    _grouped_bar(ax, labels, metrics, lambda label, metric: _mean(grouped.get((label, metric), [])))
    _finish_axes(ax, title, "Runtime strategy", "Benchmark metric")


def _plot_ablation(ax: Any, rows: List[Dict[str, Any]], title: str) -> None:
    grouped: Dict[str, Dict[str, List[float]]] = {}
    for row in rows:
        label = str(row.get("ablation") or row.get("method") or "unknown").replace("without_", "-")
        grouped.setdefault(label, {"task": [], "recovery": []})
        grouped[label]["task"].append(_as_float(row.get("task_success_rate")) or 0.0)
        grouped[label]["recovery"].append(_as_float(row.get("recovery_success_rate")) or 0.0)
    preferred = ["adagentflow_rt", "retry_only", "-contract_monitor", "-fault_localizer", "-bounded_recovery", "-event_trace"]
    labels = [label for label in preferred if label in grouped] + sorted(label for label in grouped if label not in preferred)
    success = [_mean(grouped[label]["task"]) for label in labels]
    recovery = [_mean(grouped[label]["recovery"]) for label in labels]
    x_positions = list(range(len(labels)))
    width = 0.38
    ax.bar([x - width / 2 for x in x_positions], success, width=width, label="Task success", color="#4f81bd")
    ax.bar([x + width / 2 for x in x_positions], recovery, width=width, label="Recovery success", color="#9bbb59")
    ax.set_xticks(x_positions, [_method_label(label) for label in labels], rotation=24, ha="right", fontsize=8)
    _finish_axes(ax, title, "Ablation", "Rate", ylim=(0, 1))


def _plot_table_summary(ax: Any, rows: List[Dict[str, Any]], title: str) -> None:
    ax.set_title(title, fontsize=11, weight="bold")
    ax.set_axis_off()
    ax.text(0.02, 0.9, f"{len(rows)} data rows", fontsize=10, weight="bold")
    for idx, row in enumerate(rows[:10]):
        compact = ", ".join(f"{k}={v}" for k, v in row.items() if v is not None)
        ax.text(0.02, 0.8 - idx * 0.07, compact[:110], fontsize=7.5)


def _grouped_bar(ax: Any, labels: List[str], metrics: List[str], value_for: Callable[[str, str], float]) -> None:
    width = 0.8 / max(len(metrics), 1)
    x_positions = list(range(len(labels)))
    colors = ["#4f81bd", "#c0504d", "#9bbb59", "#8064a2"]
    for idx, metric in enumerate(metrics):
        xs = [x - 0.4 + width / 2 + idx * width for x in x_positions]
        ax.bar(xs, [value_for(label, metric) for label in labels], width=width, label=metric.replace("_", " "), color=colors[idx % len(colors)])
    ax.set_xticks(x_positions, labels, rotation=18, ha="right", fontsize=7)


def _finish_axes(ax: Any, title: str, xlabel: str, ylabel: str, *, ylim: tuple[float, float] | None = None) -> None:
    ax.set_title(title, fontsize=11, weight="bold")
    ax.set_xlabel(xlabel, fontsize=9)
    ax.set_ylabel(ylabel, fontsize=9)
    if ylim:
        ax.set_ylim(*ylim)
    ax.grid(axis="y", color="#dddddd", linewidth=0.7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    if ax.get_legend_handles_labels()[0]:
        ax.legend(fontsize=7, frameon=False, loc="best")


def _method_label(value: Any) -> str:
    return str(value or "unknown").replace("adagentflow_rt", "AdAgentFlow-RT").replace("_", "-")


def _as_float(value: Any) -> float | None:
    try:
        if value in (None, "", "smoke", "mixed"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _lighten(hex_color: str) -> str:
    value = hex_color.lstrip("#")
    rgb = [int(value[i : i + 2], 16) for i in (0, 2, 4)]
    light = [int(channel + (255 - channel) * 0.72) for channel in rgb]
    return "#" + "".join(f"{channel:02x}" for channel in light)


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
