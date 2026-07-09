"""压测指标收集器 - 记录每个任务、每个 step 的执行指标"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class TaskMetric:
    """单个任务的指标"""

    task_id: str
    started_at: float
    finished_at: Optional[float] = None
    success: bool = False
    final_status: str = "unknown"
    retry_count: int = 0
    step_results: Dict[str, str] = field(default_factory=dict)
    step_latencies: Dict[str, int] = field(default_factory=dict)
    step_retry_counts: Dict[str, int] = field(default_factory=dict)
    json_failure_count: int = 0
    repair_triggered: bool = False
    went_to_dead_letter: bool = False

    @property
    def duration(self) -> float:
        if self.finished_at is None:
            return 0.0
        return self.finished_at - self.started_at


class MetricsCollector:
    """压测期间的指标汇总

    - 每个 task 的生命周期
    - 每个 step 的成功率
    - 整体吞吐 / 平均耗时 / P95 / 平均重试
    """

    STEP_NAMES = [
        "product_analysis",
        "script_generation",
        "storyboard_planning",
        "material_suggestion",
        "quality_evaluation",
    ]

    def __init__(self, scenario: str):
        self.scenario = scenario
        self.start_time = time.time()
        self.tasks: List[TaskMetric] = []
        self.extra: Dict[str, Any] = {}

    def new_task(self, task_id: str) -> TaskMetric:
        m = TaskMetric(task_id=task_id, started_at=time.time())
        self.tasks.append(m)
        return m

    def record_step(self, task_metric: TaskMetric, step_id: str,
                    success: bool, latency_ms: int, retry_count: int,
                    json_failed: bool = False):
        task_metric.step_results[step_id] = "success" if success else "failed"
        task_metric.step_latencies[step_id] = latency_ms
        task_metric.step_retry_counts[step_id] = retry_count
        if json_failed:
            task_metric.json_failure_count += 1

    def finalize_task(self, task_metric: TaskMetric,
                      success: bool, status: str, retry_count: int):
        task_metric.finished_at = time.time()
        task_metric.success = success
        task_metric.final_status = status
        task_metric.retry_count = retry_count

    def set_extra(self, key: str, value: Any):
        self.extra[key] = value

    # ================================================================
    # 聚合
    # ================================================================
    def aggregate(self) -> Dict[str, Any]:
        finished = [t for t in self.tasks if t.finished_at is not None]
        durations = sorted([t.duration for t in finished if t.duration > 0])

        n_total = len(self.tasks)
        n_success = sum(1 for t in self.tasks if t.success)
        n_dead_letter = sum(1 for t in self.tasks if t.went_to_dead_letter)
        n_repair = sum(1 for t in self.tasks if t.repair_triggered)

        total_retry = sum(t.retry_count for t in self.tasks)
        avg_retry = total_retry / n_total if n_total else 0

        # 节点级成功率
        step_stats: Dict[str, Dict[str, int]] = {}
        for step in self.STEP_NAMES:
            total = sum(1 for t in self.tasks if step in t.step_results)
            success = sum(1 for t in self.tasks if t.step_results.get(step) == "success")
            failed = sum(1 for t in self.tasks if t.step_results.get(step) == "failed")
            json_failed = sum(
                1 for t in self.tasks
                if step in t.step_results and t.step_retry_counts.get(step, 0) > 0
            )
            step_stats[step] = {
                "total": total,
                "success": success,
                "failed": failed,
                "success_rate": round(success / total * 100, 2) if total else 0.0,
                "json_failures": json_failed,
            }

        # 平均 step 延迟
        step_latencies: Dict[str, float] = {}
        for step in self.STEP_NAMES:
            lats = [t.step_latencies[step] for t in self.tasks if step in t.step_latencies]
            step_latencies[step] = round(sum(lats) / len(lats), 1) if lats else 0.0

        # JSON 失败总数
        json_failure_tasks = sum(1 for t in self.tasks if t.json_failure_count > 0)
        json_failure_rate = round(json_failure_tasks / n_total * 100, 2) if n_total else 0.0

        elapsed = time.time() - self.start_time
        throughput = n_total / elapsed if elapsed > 0 else 0.0
        e2e_throughput = n_success / elapsed if elapsed > 0 else 0.0

        return {
            "scenario": self.scenario,
            "summary": {
                "total_tasks": n_total,
                "success_tasks": n_success,
                "success_rate": round(n_success / n_total * 100, 2) if n_total else 0.0,
                "dead_letter_tasks": n_dead_letter,
                "repair_triggered_tasks": n_repair,
                "json_failure_tasks": json_failure_tasks,
                "json_failure_rate": json_failure_rate,
                "elapsed_seconds": round(elapsed, 2),
                "throughput_tasks_per_sec": round(throughput, 2),
                "e2e_throughput_per_sec": round(e2e_throughput, 2),
            },
            "latency": {
                "avg_seconds": round(sum(durations) / len(durations), 3) if durations else 0.0,
                "p50_seconds": round(_percentile(durations, 50), 3),
                "p95_seconds": round(_percentile(durations, 95), 3),
                "p99_seconds": round(_percentile(durations, 99), 3),
                "max_seconds": round(max(durations), 3) if durations else 0.0,
                "min_seconds": round(min(durations), 3) if durations else 0.0,
            },
            "retry": {
                "total_retries": total_retry,
                "avg_retry_per_task": round(avg_retry, 3),
                "max_retry_per_task": max((t.retry_count for t in self.tasks), default=0),
            },
            "step_stats": step_stats,
            "step_avg_latency_ms": step_latencies,
            "extra": self.extra,
            "raw_tasks": [asdict(t) for t in self.tasks],
        }

    def snapshot(self) -> Dict[str, Any]:
        """当前 scenario 的指标"""
        return self.aggregate()

    def snapshot_all(self) -> Dict[str, Any]:
        """用于 report_generator 的格式：{scenario: metrics}"""
        return {self.scenario: self.aggregate()}


def _percentile(sorted_list: List[float], p: int) -> float:
    if not sorted_list:
        return 0.0
    k = (len(sorted_list) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(sorted_list) - 1)
    if f == c:
        return sorted_list[f]
    return sorted_list[f] + (sorted_list[c] - sorted_list[f]) * (k - f)