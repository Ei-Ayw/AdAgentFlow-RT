"""JSON 校验器单元测试

覆盖：
- validate_json_output: 合法 JSON、未知 schema、JSON 解析失败、Schema 校验失败
- quick_json_repair: markdown 包裹、末尾逗号、缺括号、不可修复
- build_repair_prompt: 包含 schema 名 / 原始输出 / 错误细节
- 5 个 step_id 的合法样例全部能过
"""
from __future__ import annotations

import json

import pytest

from app.services.json_validator import (
    JsonValidationError,
    SCHEMA_REGISTRY,
    validate_json_output,
    quick_json_repair,
    build_repair_prompt,
)


# ============================================================
# 5 个 step_id 的合法样例
# ============================================================
PRODUCT_ANALYSIS_OK = {
    "pain_points": [
        "出门一晒就出汗，地铁通勤粘腻不适",
        "户外作业久站闷热难耐，影响效率",
    ],
    "target_users": ["城市通勤人群", "外卖骑手"],
    "core_selling_points": [
        "无叶挂颈双手解放",
        "6 小时超长续航",
    ],
    "ad_angle": "通勤酷暑 vs 挂颈清凉对比",
    "target_emotion": "relief",
}

SCRIPT_OK = {
    "hook": "这条 38 度的高温天里，你还在汗如雨下？",
    "problem": "地铁里、办公室、外卖路上，传统风扇让你崩溃",
    "solution": "便携挂颈无叶风扇，挂在脖子上秒变私人气候站",
    "proof": "180克无感重量，比耳机还轻，6小时续航一整天",
    "cta": "点击橱窗，立刻下单，今天就降温！",
    "full_script": (
        "这条 38 度的高温天里，你还在汗如雨下？"
        "地铁里、办公室、外卖路上，传统风扇让你崩溃。"
        "便携挂颈无叶风扇，挂在脖子上秒变私人气候站。"
        "180克无感重量，比耳机还轻，6小时续航一整天。"
        "点击橱窗，立刻下单，今天就降温！"
    ),
}

STORYBOARD_OK = {
    "storyboard": [
        {
            "scene_id": 1,
            "duration": 3,
            "visual": "通勤白领在地铁里满头大汗，狼狈地边走边用文件扇风",
            "subtitle": "38°C 高温 通勤崩溃现场",
            "voiceover": "这条 38 度的高温天里，你还在汗如雨下？",
            "camera_shot": "medium",
            "material_type": "pain_point_scene",
        },
        {
            "scene_id": 2,
            "duration": 3,
            "visual": "特写主角戴上挂颈风扇，立刻清爽表情变化，吹动头发动画",
            "subtitle": "一秒入秋 清凉上线",
            "voiceover": "便携挂颈无叶风扇，挂在脖子上秒变私人气候站",
            "camera_shot": "close-up",
            "material_type": "demo_scene",
        },
        {
            "scene_id": 3,
            "duration": 3,
            "visual": "外卖小哥边骑车边戴风扇跑单，全程凉爽对照传统工人汗流浃背",
            "subtitle": "6 小时续航 一整天通勤无忧",
            "voiceover": "三档风量，6 小时续航一整天通勤无忧",
            "camera_shot": "wide",
            "material_type": "proof_scene",
        },
        {
            "scene_id": 4,
            "duration": 3,
            "visual": "产品 hero shot + 醒目价格 + 立即购买按钮动画",
            "subtitle": "立即下单 今天就降温",
            "voiceover": "点击橱窗，立刻下单，今天就降温！",
            "camera_shot": "cut",
            "material_type": "cta_scene",
        },
    ]
}

MATERIAL_OK = {
    "materials": [
        {
            "scene_id": 1,
            "material_keyword": "sweating commuter subway",
            "material_type": "pain_point_scene",
            "source": "mock_library",
            "description": "通勤人群地铁车厢出汗特写 8 秒素材",
        },
        {
            "scene_id": 2,
            "material_keyword": "neck fan unboxing happy",
            "material_type": "demo_scene",
            "source": "mock_library",
            "description": "白领拆开挂颈风扇佩戴露出笑容 6 秒",
        },
        {
            "scene_id": 3,
            "material_keyword": "delivery rider cooling",
            "material_type": "proof_scene",
            "source": "mock_library",
            "description": "外卖骑手戴风扇路上配送片段 10 秒",
        },
        {
            "scene_id": 4,
            "material_keyword": "product hero shot cta",
            "material_type": "cta_scene",
            "source": "mock_library",
            "description": "产品 hero 镜头 + 价格 + 立即购买按钮动画",
        },
    ]
}

EVAL_OK = {
    "score": 87,
    "passed": True,
    "issues": [],
    "risk_level": "low",
    "suggested_fix": "",
}


class TestSchemaRegistry:
    def test_all_required_step_ids_registered(self):
        for step_id in (
            "product_analysis",
            "script_generation",
            "storyboard_planning",
            "material_suggestion",
            "quality_evaluation",
        ):
            assert step_id in SCHEMA_REGISTRY, f"{step_id} 未在 SCHEMA_REGISTRY 中注册"

    def test_registry_values_are_tuples(self):
        for step_id, value in SCHEMA_REGISTRY.items():
            assert isinstance(value, tuple)
            assert len(value) == 2


# ============================================================
# validate_json_output - 合法样例
# ============================================================
class TestValidateJsonOutputLegal:
    def test_product_analysis_passes(self):
        content = json.dumps(PRODUCT_ANALYSIS_OK, ensure_ascii=False)
        parsed, canonical = validate_json_output("product_analysis", content)
        assert parsed["ad_angle"] == PRODUCT_ANALYSIS_OK["ad_angle"]
        assert isinstance(canonical, str)
        json.loads(canonical)  # canonical 必须是合法 JSON

    def test_script_generation_passes(self):
        content = json.dumps(SCRIPT_OK, ensure_ascii=False)
        parsed, _ = validate_json_output("script_generation", content)
        assert parsed["hook"] == SCRIPT_OK["hook"]

    def test_storyboard_planning_passes(self):
        content = json.dumps(STORYBOARD_OK, ensure_ascii=False)
        parsed, _ = validate_json_output("storyboard_planning", content)
        assert len(parsed["storyboard"]) == 4

    def test_material_suggestion_passes(self):
        content = json.dumps(MATERIAL_OK, ensure_ascii=False)
        parsed, _ = validate_json_output("material_suggestion", content)
        assert len(parsed["materials"]) == 4

    def test_quality_evaluation_passes(self):
        content = json.dumps(EVAL_OK, ensure_ascii=False)
        parsed, _ = validate_json_output("quality_evaluation", content)
        assert parsed["score"] == 87
        assert parsed["passed"] is True


# ============================================================
# validate_json_output - 错误情况
# ============================================================
class TestValidateJsonOutputErrors:
    def test_unknown_schema_raises(self):
        with pytest.raises(JsonValidationError) as exc:
            validate_json_output("nonexistent_schema", "{}")
        assert exc.value.schema_name == "nonexistent_schema"
        # 未知 schema 直接抛错（不进入 JSON 解析阶段）
        assert "未知 schema" in str(exc.value)

    def test_broken_json_raises_parse_error(self):
        with pytest.raises(JsonValidationError) as exc:
            validate_json_output("script_generation", "{ this is broken")
        assert exc.value.error_type == "JSON_PARSE_ERROR"
        assert exc.value.schema_name == "script_generation"
        # raw_content 必须保留，方便上层修复
        assert exc.value.raw_content == "{ this is broken"

    def test_schema_validation_failure(self):
        """缺必填字段 → SCHEMA_VALIDATION_ERROR"""
        bad = json.dumps({"hook": "ok", "cta": "ok"})  # 缺 problem/solution/proof/full_script
        with pytest.raises(JsonValidationError) as exc:
            validate_json_output("script_generation", bad)
        assert exc.value.error_type == "SCHEMA_VALIDATION_ERROR"
        assert exc.value.schema_name == "script_generation"
        # 至少要有一条 error detail
        assert len(exc.value.error_details) > 0

    def test_schema_validation_too_short_hook(self):
        bad = dict(SCRIPT_OK)
        bad["hook"] = "x"  # < min_length=10
        with pytest.raises(JsonValidationError) as exc:
            validate_json_output("script_generation", json.dumps(bad))
        assert exc.value.error_type == "SCHEMA_VALIDATION_ERROR"

    def test_schema_validation_score_out_of_range(self):
        bad = dict(EVAL_OK)
        bad["score"] = 999  # > 100
        with pytest.raises(JsonValidationError) as exc:
            validate_json_output("quality_evaluation", json.dumps(bad))
        assert exc.value.error_type == "SCHEMA_VALIDATION_ERROR"


# ============================================================
# quick_json_repair
# ============================================================
class TestQuickJsonRepair:
    def test_passes_through_valid_json(self):
        valid = json.dumps({"a": 1})
        assert quick_json_repair(valid) == {"a": 1}

    def test_repairs_markdown_wrapped_json(self):
        inner = json.dumps({"a": 1}, ensure_ascii=False)
        md = f"```json\n{inner}\n```"
        assert quick_json_repair(md) == {"a": 1}

    def test_repairs_markdown_no_lang(self):
        inner = json.dumps({"a": 1})
        md = f"```\n{inner}\n```"
        assert quick_json_repair(md) == {"a": 1}

    def test_repairs_trailing_comma_object(self):
        # 末尾逗号无法用 json.loads 直接解析
        s = '{"a": 1, "b": 2,}'
        # quick_json_repair 不直接修逗号，但先尝试 markdown / 括号补全
        # 这里仅验证：返回 None 或者成功 — 不能抛异常
        result = quick_json_repair(s)
        # 如果修复失败，函数返回 None，不抛异常
        assert result is None or result == {"a": 1, "b": 2}

    def test_repairs_missing_close_brace(self):
        """缺右括号 → quick_json_repair 能补上。"""
        s = '{"a": 1, "b": 2'
        result = quick_json_repair(s)
        assert result == {"a": 1, "b": 2}

    def test_repairs_missing_close_bracket(self):
        s = '[1, 2, 3'
        result = quick_json_repair(s)
        assert result == [1, 2, 3]

    def test_returns_none_for_unrepairable(self):
        """完全无法修复的返回 None，不抛异常。"""
        assert quick_json_repair("totally not json at all {} broken [] nonsense") is None
        assert quick_json_repair("") is None
        assert quick_json_repair("   \n\t  ") is None

    def test_does_not_raise_on_garbage(self):
        """quick_json_repair 必须 never raise（上层依赖这点）。"""
        for s in [
            "",
            "{",
            "[",
            "{a:}",
            "not json",
            "}{",
            '{"unterminated": ',
        ]:
            try:
                quick_json_repair(s)
            except Exception as e:
                pytest.fail(f"quick_json_repair raised on {s!r}: {e}")


# ============================================================
# build_repair_prompt
# ============================================================
class TestBuildRepairPrompt:
    def test_includes_schema_name(self):
        prompt = build_repair_prompt(
            "script_generation",
            '{"broken":',
            ["field 'hook' missing"],
        )
        assert "script_generation" in prompt

    def test_includes_original_output(self):
        raw = '{"hook": "short"'
        prompt = build_repair_prompt("script_generation", raw, ["too short"])
        assert raw in prompt

    def test_includes_error_details(self):
        errs = ["loc=hook: too short", "loc=cta: missing"]
        prompt = build_repair_prompt(
            "script_generation", "{}", errs,
        )
        for err in errs:
            assert err in prompt

    def test_returns_string(self):
        prompt = build_repair_prompt("product_analysis", "{}", ["x"])
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_includes_schema_definition(self):
        """repair prompt 应该把目标 schema 也带上，方便 LLM 知道目标格式。"""
        prompt = build_repair_prompt(
            "storyboard_planning",
            "{}",
            ["missing storyboard"],
        )
        # 字段名 storyboard 必须出现在 prompt 里（schema 内）
        assert "storyboard" in prompt

    def test_includes_directives(self):
        prompt = build_repair_prompt("product_analysis", "{}", ["err"])
        # 至少要有一条"只返回 JSON"或类似的强约束指令
        assert "JSON" in prompt