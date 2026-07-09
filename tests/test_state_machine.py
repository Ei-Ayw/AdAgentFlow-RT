"""状态机单元测试

覆盖范围：
- TaskStatus 所有合法转移
- TaskStatus 非法转移抛 StateMachineError
- StepStatus 所有合法转移
- StepStatus 非法转移抛 StateMachineError
- WORKFLOW_STEPS 顺序
- next_step_or_done 行为
- can_transition_* 非法 status 字符串处理
"""
from __future__ import annotations

import pytest

from app.core.state_machine import (
    TaskStatus,
    StepStatus,
    TASK_TRANSITIONS,
    STEP_TRANSITIONS,
    WORKFLOW_STEPS,
    STEP_NAME_DISPLAY,
    StateMachineError,
    can_transition_task,
    can_transition_step,
    assert_transition_task,
    assert_transition_step,
    next_step_or_done,
)


# ============================================================
# TaskStatus 合法转移
# ============================================================
class TestTaskStatusLegalTransitions:
    """逐条覆盖 TASK_TRANSITIONS 表里所有合法转移。"""

    @pytest.mark.parametrize(
        "frm,to",
        sorted(
            [(f.value, t.value) for f, ts in TASK_TRANSITIONS.items() for t in ts],
            key=lambda x: (x[0], x[1]),
        ),
    )
    def test_legal_task_transition(self, frm, to):
        assert can_transition_task(frm, to) is True
        # 不抛异常
        assert_transition_task(frm, to)

    def test_created_can_go_to_queued(self):
        assert can_transition_task(TaskStatus.CREATED.value, TaskStatus.QUEUED.value)

    def test_created_can_go_to_running(self):
        assert can_transition_task(TaskStatus.CREATED.value, TaskStatus.RUNNING.value)

    def test_created_can_go_to_failed(self):
        assert can_transition_task(TaskStatus.CREATED.value, TaskStatus.FAILED.value)

    def test_queued_can_go_to_running(self):
        assert can_transition_task(TaskStatus.QUEUED.value, TaskStatus.RUNNING.value)

    def test_running_can_go_to_evaluating(self):
        assert can_transition_task(TaskStatus.RUNNING.value, TaskStatus.EVALUATING.value)

    def test_running_can_go_to_success(self):
        assert can_transition_task(TaskStatus.RUNNING.value, TaskStatus.SUCCESS.value)

    def test_running_can_go_to_retrying(self):
        assert can_transition_task(TaskStatus.RUNNING.value, TaskStatus.RETRYING.value)

    def test_running_can_go_to_dead_letter(self):
        assert can_transition_task(TaskStatus.RUNNING.value, TaskStatus.DEAD_LETTER.value)

    def test_evaluating_can_go_to_success(self):
        assert can_transition_task(TaskStatus.EVALUATING.value, TaskStatus.SUCCESS.value)

    def test_evaluating_can_go_to_manual_review(self):
        assert can_transition_task(TaskStatus.EVALUATING.value, TaskStatus.MANUAL_REVIEW.value)

    def test_retrying_can_go_to_dead_letter(self):
        assert can_transition_task(TaskStatus.RETRYING.value, TaskStatus.DEAD_LETTER.value)

    def test_manual_review_can_go_to_queued(self):
        assert can_transition_task(TaskStatus.MANUAL_REVIEW.value, TaskStatus.QUEUED.value)

    def test_failed_can_go_to_retrying(self):
        assert can_transition_task(TaskStatus.FAILED.value, TaskStatus.RETRYING.value)

    def test_failed_can_go_to_dead_letter(self):
        assert can_transition_task(TaskStatus.FAILED.value, TaskStatus.DEAD_LETTER.value)

    def test_dead_letter_can_go_to_queued(self):
        assert can_transition_task(TaskStatus.DEAD_LETTER.value, TaskStatus.QUEUED.value)

    def test_dead_letter_can_go_to_success(self):
        assert can_transition_task(TaskStatus.DEAD_LETTER.value, TaskStatus.SUCCESS.value)


# ============================================================
# TaskStatus 非法转移
# ============================================================
class TestTaskStatusIllegalTransitions:
    """终态、跳级转移都应该被拒绝。"""

    def test_success_is_terminal(self):
        """SUCCESS 是终态，不能转出。"""
        for to in TaskStatus:
            if to == TaskStatus.SUCCESS:
                continue
            assert not can_transition_task(TaskStatus.SUCCESS.value, to.value), (
                f"SUCCESS -> {to.value} 应被拒绝"
            )

    def test_success_to_running_blocked(self):
        with pytest.raises(StateMachineError):
            assert_transition_task(TaskStatus.SUCCESS.value, TaskStatus.RUNNING.value)

    def test_created_cannot_skip_to_success(self):
        with pytest.raises(StateMachineError):
            assert_transition_task(TaskStatus.CREATED.value, TaskStatus.SUCCESS.value)

    def test_created_cannot_skip_to_evaluating(self):
        with pytest.raises(StateMachineError):
            assert_transition_task(TaskStatus.CREATED.value, TaskStatus.EVALUATING.value)

    def test_queued_cannot_skip_to_success(self):
        with pytest.raises(StateMachineError):
            assert_transition_task(TaskStatus.QUEUED.value, TaskStatus.SUCCESS.value)

    def test_unknown_status_returns_false(self):
        assert not can_transition_task("nonexistent", TaskStatus.RUNNING.value)
        assert not can_transition_task(TaskStatus.RUNNING.value, "nonexistent")

    def test_unknown_status_assert_raises(self):
        with pytest.raises(StateMachineError):
            assert_transition_task("nonexistent", TaskStatus.RUNNING.value)

    def test_queued_cannot_go_to_evaluating_directly(self):
        """QUEUED -> EVALUATING 没有定义，应抛错。"""
        assert not can_transition_task(TaskStatus.QUEUED.value, TaskStatus.EVALUATING.value)


# ============================================================
# StepStatus 合法转移
# ============================================================
class TestStepStatusLegalTransitions:
    @pytest.mark.parametrize(
        "frm,to",
        sorted(
            [(f.value, t.value) for f, ts in STEP_TRANSITIONS.items() for t in ts],
            key=lambda x: (x[0], x[1]),
        ),
    )
    def test_legal_step_transition(self, frm, to):
        assert can_transition_step(frm, to) is True
        assert_transition_step(frm, to)

    def test_pending_to_running(self):
        assert can_transition_step(StepStatus.PENDING.value, StepStatus.RUNNING.value)

    def test_pending_to_skipped(self):
        assert can_transition_step(StepStatus.PENDING.value, StepStatus.SKIPPED.value)

    def test_running_to_success(self):
        assert can_transition_step(StepStatus.RUNNING.value, StepStatus.SUCCESS.value)

    def test_running_to_failed(self):
        assert can_transition_step(StepStatus.RUNNING.value, StepStatus.FAILED.value)

    def test_running_to_retrying(self):
        assert can_transition_step(StepStatus.RUNNING.value, StepStatus.RETRYING.value)

    def test_failed_to_retrying(self):
        assert can_transition_step(StepStatus.FAILED.value, StepStatus.RETRYING.value)

    def test_failed_to_skipped(self):
        assert can_transition_step(StepStatus.FAILED.value, StepStatus.SKIPPED.value)

    def test_retrying_to_running(self):
        assert can_transition_step(StepStatus.RETRYING.value, StepStatus.RUNNING.value)

    def test_retrying_to_skipped(self):
        assert can_transition_step(StepStatus.RETRYING.value, StepStatus.SKIPPED.value)


# ============================================================
# StepStatus 非法转移
# ============================================================
class TestStepStatusIllegalTransitions:
    def test_success_is_terminal(self):
        for to in StepStatus:
            if to == StepStatus.SUCCESS:
                continue
            assert not can_transition_step(StepStatus.SUCCESS.value, to.value)

    def test_skipped_is_terminal(self):
        for to in StepStatus:
            if to == StepStatus.SKIPPED:
                continue
            assert not can_transition_step(StepStatus.SKIPPED.value, to.value)

    def test_pending_to_success_blocked(self):
        assert not can_transition_step(StepStatus.PENDING.value, StepStatus.SUCCESS.value)
        with pytest.raises(StateMachineError):
            assert_transition_step(StepStatus.PENDING.value, StepStatus.SUCCESS.value)

    def test_pending_to_failed_blocked(self):
        with pytest.raises(StateMachineError):
            assert_transition_step(StepStatus.PENDING.value, StepStatus.FAILED.value)

    def test_unknown_step_status_returns_false(self):
        assert not can_transition_step("nonexistent", StepStatus.RUNNING.value)


# ============================================================
# WORKFLOW_STEPS
# ============================================================
class TestWorkflowSteps:
    def test_workflow_steps_order(self):
        assert WORKFLOW_STEPS == [
            "product_analysis",
            "script_generation",
            "storyboard_planning",
            "material_suggestion",
            "quality_evaluation",
        ]

    def test_workflow_steps_unique(self):
        assert len(WORKFLOW_STEPS) == len(set(WORKFLOW_STEPS))

    def test_workflow_steps_contains_all_required(self):
        for step_id in (
            "product_analysis",
            "script_generation",
            "storyboard_planning",
            "material_suggestion",
            "quality_evaluation",
        ):
            assert step_id in WORKFLOW_STEPS

    def test_step_name_display_covers_workflow_steps(self):
        for step_id in WORKFLOW_STEPS:
            assert step_id in STEP_NAME_DISPLAY

    def test_step_name_display_repair_present(self):
        assert "repair" in STEP_NAME_DISPLAY


# ============================================================
# next_step_or_done
# ============================================================
class TestNextStepOrDone:
    def test_returns_next_step(self):
        assert next_step_or_done("product_analysis") == "script_generation"
        assert next_step_or_done("script_generation") == "storyboard_planning"
        assert next_step_or_done("storyboard_planning") == "material_suggestion"
        assert next_step_or_done("material_suggestion") == "quality_evaluation"

    def test_returns_none_for_last_step(self):
        assert next_step_or_done("quality_evaluation") is None

    def test_returns_none_for_unknown_step(self):
        assert next_step_or_done("nonexistent") is None
        assert next_step_or_done("") is None

    def test_repair_is_not_in_workflow(self):
        """repair 不是 WORKFLOW_STEPS 的一员（它是旁路分支），应该返回 None。"""
        assert next_step_or_done("repair") is None