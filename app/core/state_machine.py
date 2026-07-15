"""任务状态机 - 任务级 + 节点级"""
from enum import Enum
from typing import Dict, Set, Tuple


class TaskStatus(str, Enum):
    """任务级状态枚举"""

    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    EVALUATING = "evaluating"
    RETRYING = "retrying"
    SUCCESS = "success"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    MANUAL_REVIEW = "manual_review"


class StepStatus(str, Enum):
    """节点级状态枚举"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    SKIPPED = "skipped"


# ============================================================
# 状态机定义：from -> set of allowed to
# ============================================================
TASK_TRANSITIONS: Dict[TaskStatus, Set[TaskStatus]] = {
    TaskStatus.CREATED: {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.FAILED},
    TaskStatus.QUEUED: {TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.DEAD_LETTER},
    TaskStatus.RUNNING: {
        TaskStatus.EVALUATING,
        TaskStatus.SUCCESS,
        TaskStatus.FAILED,
        TaskStatus.RETRYING,
        TaskStatus.DEAD_LETTER,
        TaskStatus.QUEUED,
    },
    TaskStatus.EVALUATING: {
        TaskStatus.SUCCESS,
        TaskStatus.RETRYING,
        TaskStatus.FAILED,
        TaskStatus.MANUAL_REVIEW,
        TaskStatus.DEAD_LETTER,
        TaskStatus.QUEUED,
    },
    TaskStatus.RETRYING: {
        TaskStatus.QUEUED,
        TaskStatus.RUNNING,
        TaskStatus.DEAD_LETTER,
        TaskStatus.FAILED,
        TaskStatus.MANUAL_REVIEW,
    },
    TaskStatus.MANUAL_REVIEW: {TaskStatus.QUEUED, TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.DEAD_LETTER},
    TaskStatus.SUCCESS: set(),  # 终态
    TaskStatus.FAILED: {TaskStatus.RETRYING, TaskStatus.DEAD_LETTER, TaskStatus.MANUAL_REVIEW},
    TaskStatus.DEAD_LETTER: {TaskStatus.QUEUED, TaskStatus.MANUAL_REVIEW, TaskStatus.SUCCESS},
}


STEP_TRANSITIONS: Dict[StepStatus, Set[StepStatus]] = {
    StepStatus.PENDING: {StepStatus.RUNNING, StepStatus.SKIPPED},
    StepStatus.RUNNING: {StepStatus.SUCCESS, StepStatus.FAILED, StepStatus.RETRYING},
    StepStatus.SUCCESS: set(),
    StepStatus.FAILED: {StepStatus.RETRYING, StepStatus.SKIPPED},
    StepStatus.RETRYING: {StepStatus.RUNNING, StepStatus.SKIPPED},
    StepStatus.SKIPPED: set(),
}


class StateMachineError(Exception):
    """非法状态转移异常"""

    pass


def can_transition_task(from_status: str, to_status: str) -> bool:
    """判断任务状态转移是否合法"""
    try:
        fs = TaskStatus(from_status)
        ts = TaskStatus(to_status)
    except ValueError:
        return False
    return ts in TASK_TRANSITIONS.get(fs, set())


def assert_transition_task(from_status: str, to_status: str) -> None:
    """断言状态合法，否则抛 StateMachineError"""
    if not can_transition_task(from_status, to_status):
        raise StateMachineError(
            f"非法任务状态转移: {from_status} -> {to_status}",
        )


def can_transition_step(from_status: str, to_status: str) -> bool:
    """判断节点状态转移是否合法"""
    try:
        fs = StepStatus(from_status)
        ts = StepStatus(to_status)
    except ValueError:
        return False
    return ts in STEP_TRANSITIONS.get(fs, set())


def assert_transition_step(from_status: str, to_status: str) -> None:
    if not can_transition_step(from_status, to_status):
        raise StateMachineError(f"非法节点状态转移: {from_status} -> {to_status}")


# ============================================================
# 工作流编排：定义节点顺序
# ============================================================
WORKFLOW_STEPS = [
    "product_analysis",
    "script_generation",
    "storyboard_planning",
    "material_suggestion",
    "image_generation",
    "video_generation",
    "composition",
    "quality_evaluation",
]

STEP_NAME_DISPLAY = {
    "product_analysis": "商品理解 Agent",
    "script_generation": "广告脚本 Agent",
    "storyboard_planning": "分镜规划 Agent",
    "material_suggestion": "素材建议 Agent",
    "image_generation": "关键帧生成",
    "video_generation": "视频片段生成",
    "composition": "成片合成",
    "quality_evaluation": "质量评估 Agent",
    "repair": "失败修复 Agent",
}


def next_step_or_done(current_step: str) -> str | None:
    """返回当前步骤的下一节点；没有就返回 None"""
    try:
        idx = WORKFLOW_STEPS.index(current_step)
        if idx + 1 < len(WORKFLOW_STEPS):
            return WORKFLOW_STEPS[idx + 1]
        return None
    except ValueError:
        return None
