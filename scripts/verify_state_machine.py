"""状态机和 JSON 校验快速 smoke test"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_state_machine():
    from app.core.state_machine import (
        TaskStatus,
        StepStatus,
        can_transition_task,
        can_transition_step,
        assert_transition_task,
        StateMachineError,
    )

    # 合法转移
    assert can_transition_task(TaskStatus.CREATED.value, TaskStatus.QUEUED.value)
    assert can_transition_task(TaskStatus.QUEUED.value, TaskStatus.RUNNING.value)
    assert can_transition_task(TaskStatus.RUNNING.value, TaskStatus.EVALUATING.value)
    assert can_transition_task(TaskStatus.EVALUATING.value, TaskStatus.SUCCESS.value)
    print("✅ 合法任务状态转移测试通过")

    # 非法转移
    assert not can_transition_task(TaskStatus.SUCCESS.value, TaskStatus.RUNNING.value)
    assert not can_transition_task(TaskStatus.CREATED.value, TaskStatus.SUCCESS.value)
    print("✅ 非法任务状态转移拦截测试通过")

    # 抛错
    try:
        assert_transition_task(TaskStatus.SUCCESS.value, TaskStatus.RUNNING.value)
        raise AssertionError("应该抛错")
    except StateMachineError:
        print("✅ StateMachineError 抛错测试通过")

    # 节点
    assert can_transition_step(StepStatus.PENDING.value, StepStatus.RUNNING.value)
    assert can_transition_step(StepStatus.RUNNING.value, StepStatus.SUCCESS.value)
    assert can_transition_step(StepStatus.FAILED.value, StepStatus.RETRYING.value)
    print("✅ 节点状态转移测试通过")


def test_json_validator():
    from app.services.json_validator import validate_json_output, JsonValidationError, quick_json_repair, build_repair_prompt
    import json

    # 合法 JSON
    valid_script = json.dumps({
        "hook": "这条高温天里你还在汗如雨下？",
        "problem": "地铁里、办公室、外卖路上，传统风扇让你崩溃",
        "solution": "便携挂颈无叶风扇，挂在脖子上秒变私人气候站",
        "proof": "180克无感重量，6小时续航一整天",
        "cta": "点击橱窗，立刻下单！",
        "full_script": "完整脚本示例足够长度的字符。" * 6,
    }, ensure_ascii=False)
    parsed, _ = validate_json_output("script_generation", valid_script)
    assert parsed["hook"] == "这条高温天里你还在汗如雨下？"
    print("✅ 合法 JSON 通过")

    # 非法 JSON
    try:
        validate_json_output("script_generation", "{ this is broken")
        raise AssertionError("应该失败")
    except JsonValidationError as e:
        assert e.error_type == "JSON_PARSE_ERROR"
        print(f"✅ JSON 解析失败捕获: {e.error_type}")

    # Schema 不匹配
    try:
        validate_json_output("script_generation", json.dumps({
            "hook": "ok",
            # 缺 problem / solution 等必填
            "cta": "ok"
        }))
        raise AssertionError("应该失败")
    except JsonValidationError as e:
        assert e.error_type == "SCHEMA_VALIDATION_ERROR"
        print(f"✅ Schema 不匹配捕获: {e.error_type}")

    # quick repair - markdown 包裹
    md_json = "```json\n" + json.dumps({
        "hook": "ok" * 5,
        "problem": "ok" * 5,
        "solution": "ok" * 5,
        "proof": "ok" * 5,
        "cta": "ok" * 5,
        "full_script": "ok" * 30,
    }, ensure_ascii=False) + "\n```"
    repaired = quick_json_repair(md_json)
    assert repaired is not None
    print("✅ markdown 包裹 JSON 修复成功")

    # 修复 prompt 构造
    repair_prompt = build_repair_prompt(
        "script_generation",
        valid_script,
        ["hook too short"],
        original_system="test",
    )
    assert "script_generation" in repair_prompt
    assert "hook too short" in repair_prompt
    print("✅ 修复 prompt 构造成功")


def test_failure_codes():
    from app.core.failure_codes import FailureReason, REPAIR_STRATEGY
    assert FailureReason.JSON_PARSE_ERROR.value == "JSON_PARSE_ERROR"
    assert REPAIR_STRATEGY[FailureReason.JSON_PARSE_ERROR] == "json_repair"
    assert REPAIR_STRATEGY[FailureReason.MODEL_TIMEOUT] == "model_fallback"
    print("✅ 失败类型枚举完整")


if __name__ == "__main__":
    test_state_machine()
    test_json_validator()
    test_failure_codes()
    print("\n🎉 全部 smoke test 通过!")
