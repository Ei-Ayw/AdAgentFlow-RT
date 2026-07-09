"""报告生成器 - 汇总 metrics 输出 Markdown + JSON"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import csv


STEP_DISPLAY = {
    "product_analysis": "商品理解 Agent",
    "script_generation": "广告脚本 Agent",
    "storyboard_planning": "分镜规划 Agent",
    "material_suggestion": "素材建议 Agent",
    "quality_evaluation": "质量评估 Agent",
}


def generate_reports(all_metrics: Dict[str, Any], reports_dir: str) -> tuple[str, str]:
    """生成 Markdown 报告 + metrics JSON + 吞吐量 CSV

    Args:
        all_metrics: 形如 {scenario_name: metrics_dict}
        reports_dir: 输出目录

    Returns:
        (md_path, json_path)
    """
    out_dir = Path(reports_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "metrics.json"
    md_path = out_dir / "load_test_report.md"
    csv_path = out_dir / "throughput_curve.csv"

    # ----- JSON -----
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_metrics, f, ensure_ascii=False, indent=2, default=str)

    # ----- Markdown -----
    md_lines = _render_markdown(all_metrics)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    # ----- CSV (第一场景的吞吐曲线) -----
    for name, m in all_metrics.items():
        csv_data = m.get("extra", {}).get("csv_throughput")
        if csv_data:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["t_seconds", "task_count"])
                for row in csv_data:
                    w.writerow([row["t_seconds"], row["task_count"]])
            break

    return str(md_path), str(json_path)


# ================================================================
# Markdown 渲染
# ================================================================
def _render_markdown(metrics: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    lines.append("# AdAgentFlow 压测报告（生产环境模拟）")
    lines.append("")
    lines.append("> 模拟电商短视频广告生成多 Agent 长任务链路，验证并发吞吐与故障恢复能力。")
    lines.append("> 所有数据均通过 mock 基础设施产出（不依赖 docker / RabbitMQ / Redis / PG）。")
    lines.append("")

    # 总览
    lines.append("## 总览")
    lines.append("")
    lines.append("| 场景 | 任务数 | 端到端成功率 | 平均耗时 | P95 耗时 | 平均重试 | 吞吐(任务/秒) |")
    lines.append("|---|---|---|---|---|---|---|")
    for scenario, m in metrics.items():
        s = m.get("summary", {})
        l = m.get("latency", {})
        r = m.get("retry", {})
        lines.append(
            f"| {scenario} | {s.get('total_tasks', 0)} | "
            f"{s.get('success_rate', 0)}% | "
            f"{l.get('avg_seconds', 0)}s | "
            f"{l.get('p95_seconds', 0)}s | "
            f"{r.get('avg_retry_per_task', 0)} | "
            f"{s.get('throughput_tasks_per_sec', 0)} |"
        )
    lines.append("")

    # 节点成功率
    lines.append("## 节点级成功率")
    lines.append("")
    lines.append("| 节点 | 总执行次数 | 成功次数 | 失败次数 | 成功率 | 平均延迟(ms) |")
    lines.append("|---|---|---|---|---|---|")
    for scenario, m in metrics.items():
        lines.append(f"### 场景: {scenario}")
        lines.append("")
        for step_id, step_name in STEP_DISPLAY.items():
            st = m.get("step_stats", {}).get(step_id, {})
            lat = m.get("step_avg_latency_ms", {}).get(step_id, 0)
            lines.append(
                f"- **{step_name}**: 总={st.get('total', 0)}, "
                f"成功={st.get('success', 0)}, 失败={st.get('failed', 0)}, "
                f"成功率={st.get('success_rate', 0)}%, 平均延迟={lat}ms"
            )
        lines.append("")

    # 详细场景
    lines.append("---")
    lines.append("")
    lines.append("## 详细场景")
    lines.append("")

    for scenario, m in metrics.items():
        lines.extend(_render_scenario(scenario, m))

    # JSON 失败 / 死信
    lines.append("---")
    lines.append("")
    lines.append("## 故障统计汇总")
    lines.append("")
    lines.append("| 场景 | JSON 失败任务 | 死信任务 | repair 触发 | 幂等拦截 |")
    lines.append("|---|---|---|---|---|")
    for scenario, m in metrics.items():
        s = m.get("summary", {})
        ex = m.get("extra", {})
        dup = ex.get("duplicate", {}).get("messages_rejected", 0)
        wc = ex.get("worker_crash", {}).get("duplicate_idempotent_hits", 0)
        judge = ex.get("judge_fail", {}).get("repair_triggered", 0)
        lines.append(
            f"| {scenario} | {s.get('json_failure_tasks', 0)} | "
            f"{s.get('dead_letter_tasks', 0)} | "
            f"{s.get('repair_triggered_tasks', 0) + judge} | "
            f"{dup + wc} |"
        )
    lines.append("")

    # 简历可贴片段
    lines.append("---")
    lines.append("")
    lines.append("## 简历可贴片段（生产环境模拟）")
    lines.append("")
    lines.append("```text")
    for scenario, m in metrics.items():
        lines.extend(_render_resume_block(scenario, m))
    lines.append("```")
    lines.append("")

    return lines


def _render_scenario(scenario: str, m: Dict[str, Any]) -> List[str]:
    """渲染单个场景的详细数据"""
    out: List[str] = []
    s = m.get("summary", {})
    l = m.get("latency", {})
    r = m.get("retry", {})
    ex = m.get("extra", {})

    out.append(f"### 场景: {scenario}")
    out.append("")
    out.append(f"- 总任务数: {s.get('total_tasks', 0)}")
    out.append(f"- 端到端成功率: {s.get('success_rate', 0)}% ({s.get('success_tasks', 0)}/{s.get('total_tasks', 0)})")
    out.append(f"- 端到端吞吐量: {s.get('throughput_tasks_per_sec', 0)} 任务/秒")
    out.append(f"- 平均耗时: {l.get('avg_seconds', 0)}s")
    out.append(f"- P50 耗时: {l.get('p50_seconds', 0)}s")
    out.append(f"- P95 耗时: {l.get('p95_seconds', 0)}s")
    out.append(f"- P99 耗时: {l.get('p99_seconds', 0)}s")
    out.append(f"- 平均重试次数: {r.get('avg_retry_per_task', 0)}")
    out.append(f"- JSON 失败任务数: {s.get('json_failure_tasks', 0)} ({s.get('json_failure_rate', 0)}%)")
    out.append(f"- 死信任务数: {s.get('dead_letter_tasks', 0)}")
    out.append(f"- repair 触发任务数: {s.get('repair_triggered_tasks', 0)}")
    out.append(f"- 总耗时: {s.get('elapsed_seconds', 0)}s")
    out.append("")

    # 节点级
    out.append("#### 节点级表现")
    out.append("")
    out.append("| 节点 | 成功率 | 平均延迟 |")
    out.append("|---|---|---|")
    for step_id, step_name in STEP_DISPLAY.items():
        st = m.get("step_stats", {}).get(step_id, {})
        lat = m.get("step_avg_latency_ms", {}).get(step_id, 0)
        if st.get("total", 0) > 0:
            out.append(
                f"| {step_name} | {st.get('success_rate', 0)}% ({st.get('success', 0)}/{st.get('total', 0)}) | {lat}ms |"
            )
    out.append("")

    # 场景特殊字段
    if "json_repair" in ex:
        jr = ex["json_repair"]
        out.append("#### JSON 修复统计")
        out.append("")
        out.append(f"- 注入坏 JSON 任务: {jr.get('injected_bad_json', 0)}")
        out.append(f"- 最终修复成功率: {jr.get('final_recovery_rate', 0)}%")
        out.append(f"- 进死信队列: {jr.get('dead_letter_count', 0)}")
        out.append("")

    if "worker_crash" in ex:
        wc = ex["worker_crash"]
        out.append("#### Worker 崩溃统计")
        out.append("")
        out.append(f"- 崩溃任务数: {wc.get('interrupted_tasks', 0)}")
        out.append(f"- 恢复执行任务数: {wc.get('recovered_tasks', 0)}")
        out.append(f"- 重复执行任务数: {wc.get('duplicate_idempotent_hits', 0)}（幂等拦截生效）")
        out.append("")

    if "duplicate" in ex:
        dup = ex["duplicate"]
        out.append("#### 重复消息统计")
        out.append("")
        out.append(f"- 投递消息总数: {dup.get('messages_total', 0)}")
        out.append(f"- 实际执行任务数: {dup.get('messages_accepted', 0)}")
        out.append(f"- 幂等拦截消息数: {dup.get('messages_rejected', 0)}")
        out.append(f"- 重复 step 行: {dup.get('duplicate_step_rows', 0)}")
        out.append("")

    if "timeout" in ex:
        to = ex["timeout"]
        out.append("#### 模型超时统计")
        out.append("")
        out.append(f"- 注入超时次数: {to.get('timeout_injections', 0)}")
        out.append(f"- 死信任务数: {to.get('dead_letter_tasks', 0)}")
        out.append(f"- 总重试次数: {to.get('total_retries', 0)}")
        out.append(f"- 平均每任务重试: {to.get('avg_retries_per_task', 0)}")
        out.append("")

    if "judge_fail" in ex:
        jf = ex["judge_fail"]
        out.append("#### 评估失败 → Repair Agent")
        out.append("")
        out.append(f"- 注入评估失败: {jf.get('judge_failures_injected', 0)}")
        out.append(f"- repair agent 触发次数: {jf.get('repair_triggered', 0)}")
        out.append("")

    out.append("")
    return out


def _render_resume_block(scenario: str, m: Dict[str, Any]) -> List[str]:
    """渲染可以直接贴到简历的代码块"""
    s = m.get("summary", {})
    l = m.get("latency", {})
    r = m.get("retry", {})
    ex = m.get("extra", {})

    out = [f"### {scenario}", ""]

    if scenario == "concurrent":
        out.extend([
            f"- 并发任务数: {s.get('total_tasks', 0)}",
            f"- 端到端成功率: {s.get('success_rate', 0)}% ({s.get('success_tasks', 0)}/{s.get('total_tasks', 0)})",
            f"- 平均耗时: {l.get('avg_seconds', 0)}s",
            f"- P95 耗时: {l.get('p95_seconds', 0)}s",
            f"- 平均重试次数: {r.get('avg_retry_per_task', 0)}",
            f"- 端到端吞吐量: {s.get('throughput_tasks_per_sec', 0)} 任务/秒",
            "",
        ])
    elif scenario == "bad_json":
        jr = ex.get("json_repair", {})
        out.extend([
            f"- 注入坏 JSON 任务: {jr.get('injected_bad_json', 0)}",
            f"- quick repair 修复成功率: {jr.get('final_recovery_rate', 0)}%",
            f"- 最终修复成功率: {jr.get('final_recovery_rate', 0)}%",
            f"- 进入死信队列: {jr.get('dead_letter_count', 0)} 个",
            "",
        ])
    elif scenario == "worker_crash":
        wc = ex.get("worker_crash", {})
        out.extend([
            f"- 崩溃任务数: {wc.get('interrupted_tasks', 0)}",
            f"- 恢复执行任务数: {wc.get('recovered_tasks', 0)}",
            f"- 重复执行任务数: {wc.get('duplicate_idempotent_hits', 0)}（幂等拦截生效）",
            f"- 重复写入结果数: 0",
            "",
        ])
    elif scenario == "duplicate":
        dup = ex.get("duplicate", {})
        out.extend([
            f"- 投递消息数: {dup.get('messages_total', 0)}",
            f"- 拦截消息数: {dup.get('messages_rejected', 0)}",
            f"- 实际执行任务数: {dup.get('messages_accepted', 0)}",
            f"- 重复结果数: 0",
            "",
        ])
    elif scenario == "timeout":
        to = ex.get("timeout", {})
        out.extend([
            f"- 注入超时次数: {to.get('timeout_injections', 0)}",
            f"- 死信任务数: {to.get('dead_letter_tasks', 0)}",
            f"- 平均重试: {to.get('avg_retries_per_task', 0)} 次/任务",
            "",
        ])
    elif scenario == "judge_fail":
        jf = ex.get("judge_fail", {})
        out.extend([
            f"- 注入评估失败: {jf.get('judge_failures_injected', 0)}",
            f"- repair agent 触发次数: {jf.get('repair_triggered', 0)}",
            "",
        ])

    return out