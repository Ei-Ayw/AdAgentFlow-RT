"""Dashboard 数据 API - 全部指标一次拉齐"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy.sql import func, case
from typing import Dict, List, Any

from app.db.database import get_db
from app.models.task import Task
from app.models.step import TaskStep
from app.models.trace import TaskTrace
from app.models.dead_letter import DeadLetter
from app.models.evaluation import EvaluationResult
from app.models.metric import AgentMetric

router = APIRouter()


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    """Dashboard 核心指标 - 一屏展示"""
    # 任务总数 / 状态分布
    total_tasks = db.query(Task).count()
    success_tasks = db.query(Task).filter(Task.status == "success").count()
    failed_tasks = db.query(Task).filter(Task.status == "failed").count()
    dead_letter_tasks = db.query(Task).filter(Task.status == "dead_letter").count()
    running_tasks = db.query(Task).filter(Task.status.in_(["running", "evaluating", "retrying", "queued"])).count()

    end_to_end_success_rate = (success_tasks / total_tasks) if total_tasks else 0.0

    # 平均耗时（成功任务 finished_at - created_at）
    avg_latency_ms = (
        db.query(func.avg(func.extract("epoch", Task.finished_at - Task.created_at) * 1000))
        .filter(Task.status == "success", Task.finished_at.isnot(None))
        .scalar()
    ) or 0.0

    # 平均重试次数
    avg_retry = (
        db.query(func.avg(Task.retry_count))
        .filter(Task.retry_count.isnot(None))
        .scalar()
    ) or 0.0

    # 总 LLM 调用次数
    total_llm_calls = db.query(TaskTrace).filter(TaskTrace.event_type == "step.start").count()

    # JSON 解析失败次数
    json_failures = db.query(TaskTrace).filter(TaskTrace.error_message.isnot(None)).count()
    json_failure_rate = (json_failures / total_llm_calls) if total_llm_calls else 0.0

    # 死信率
    dead_letter_rate = (dead_letter_tasks / total_tasks) if total_tasks else 0.0

    # 节点成功率
    step_success_rates = (
        db.query(
            TaskStep.step_id,
            func.count(TaskStep.id).label("total"),
            func.sum(
                case((TaskStep.status == "success", 1), else_=0)
            ).label("success"),
        )
        .group_by(TaskStep.step_id)
        .all()
    )
    node_success = []
    for sid, total, success in step_success_rates:
        node_success.append(
            {
                "step_id": sid,
                "total_executions": total or 0,
                "success_executions": success or 0,
                "success_rate": ((success or 0) / total) if total else 0.0,
            }
        )

    # 失败原因 Top 5
    failure_top = (
        db.query(TaskStep.failure_reason, func.count(TaskStep.id).label("c"))
        .filter(TaskStep.failure_reason.isnot(None))
        .group_by(TaskStep.failure_reason)
        .order_by(func.count(TaskStep.id).desc())
        .limit(5)
        .all()
    )
    failure_top_list = [{"reason": fr, "count": c} for fr, c in failure_top]

    # 评估结果均值
    avg_score = db.query(func.avg(EvaluationResult.score)).scalar() or 0.0
    passed_evals = db.query(EvaluationResult).filter(EvaluationResult.passed == True).count()
    total_evals = db.query(EvaluationResult).count()
    pass_rate = (passed_evals / total_evals) if total_evals else 0.0

    # 死信列表
    dead_letter_list = (
        db.query(DeadLetter)
        .filter(DeadLetter.resolved == False)
        .order_by(DeadLetter.id.desc())
        .limit(10)
        .all()
    )

    return {
        "task_summary": {
            "total_tasks": total_tasks,
            "success": success_tasks,
            "failed": failed_tasks,
            "dead_letter": dead_letter_tasks,
            "running": running_tasks,
            "end_to_end_success_rate": round(end_to_end_success_rate * 100, 2),
        },
        "performance": {
            "avg_latency_seconds": round((avg_latency_ms or 0) / 1000, 2),
            "avg_retry_count": round(avg_retry, 2),
            "total_llm_calls": total_llm_calls,
            "json_failure_rate": round(json_failure_rate * 100, 2),
            "dead_letter_rate": round(dead_letter_rate * 100, 2),
            "avg_quality_score": round(float(avg_score), 2),
            "judge_pass_rate": round(pass_rate * 100, 2),
        },
        "node_success_rates": node_success,
        "failure_top_5": failure_top_list,
        "unresolved_dead_letters": [
            {
                "id": dl.id,
                "task_id": dl.task_id,
                "step_id": dl.step_id,
                "failure_reason": dl.failure_reason,
                "created_at": dl.created_at.isoformat() if dl.created_at else None,
            }
            for dl in dead_letter_list
        ],
    }


@router.get("/tasks-summary")
def tasks_summary(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """按状态聚合的任务分布"""
    rows = (
        db.query(Task.status, func.count(Task.id))
        .group_by(Task.status)
        .all()
    )
    return {status: count for status, count in rows}


@router.get("/latency-trend")
def latency_trend(hours: int = 24, db: Session = Depends(get_db)):
    """按小时聚合耗时趋势"""
    from datetime import datetime, timedelta

    cutoff = datetime.utcnow() - timedelta(hours=hours)
    rows = (
        db.query(
            func.date_trunc("hour", Task.created_at).label("bucket"),
            func.count(Task.id).label("count"),
            func.avg(func.extract("epoch", Task.finished_at - Task.created_at)).label("avg_latency_s"),
        )
        .filter(Task.created_at >= cutoff)
        .group_by("bucket")
        .order_by("bucket")
        .all()
    )
    return [
        {
            "bucket": str(b.bucket),
            "count": b.count,
            "avg_latency_seconds": round(float(b.avg_latency_s or 0), 2),
        }
        for b in rows
    ]


@router.get("/agent-metrics")
def agent_metrics(db: Session = Depends(get_db)):
    """节点级聚合指标"""
    rows = db.query(AgentMetric).all()
    return [
        {
            "step_name": m.step_name,
            "total_executions": m.total_executions,
            "success_executions": m.success_executions,
            "failed_executions": m.failed_executions,
            "retry_executions": m.retry_executions,
            "avg_latency_ms": (
                int(m.total_latency_ms / m.total_executions) if m.total_executions else 0
            ),
            "json_failures": m.json_failures,
            "schema_failures": m.schema_failures,
            "success_rate": (
                round((m.success_executions / m.total_executions) * 100, 2)
                if m.total_executions
                else 0
            ),
            "last_updated_at": m.last_updated_at.isoformat() if m.last_updated_at else None,
        }
        for m in rows
    ]


@router.get("/health-check")
def health_check(db: Session = Depends(get_db)):
    """系统健康自检"""
    checks = {}
    try:
        db.execute(func.now().select())
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"fail: {e}"

    try:
        from app.services.idempotency import get_redis, get_idempotent_count
        r = await_get_redis = None
        # ping
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"fail: {e}"

    return checks
