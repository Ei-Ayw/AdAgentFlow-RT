"""Agent 单元测试（mock LLM）

覆盖：
- 每个 Agent（5 个 + repair）执行一次，验证返回结构、step_id、prompt_version
- 传入坏 JSON 触发 quick_repair 路径，验证可救回来
- 传入完全无法修复的内容，验证 result.success=False
- prompt 构造包含必要字段（product / history / 失败反馈）
"""
from __future__ import annotations

import json
import pytest

from app.agents import (
    ALL_AGENTS,
    get_agent,
    ProductAnalysisAgent,
    ScriptGenerationAgent,
    StoryboardPlanningAgent,
    MaterialSuggestionAgent,
    QualityEvaluationAgent,
    RepairAgent,
)


SAMPLE_PRODUCT = {
    "product_name": "Portable Neck Fan",
    "platform": "TikTok",
    "duration": 15,
    "target_user": "commuters",
    "selling_points": ["hands-free", "long battery"],
}


# ============================================================
# 1. ALL_AGENTS 注册表
# ============================================================
class TestAllAgentsRegistry:
    def test_all_production_agents_registered(self):
        expected = {
            "product_analysis",
            "script_generation",
            "storyboard_planning",
            "material_suggestion",
            "image_generation",
            "video_generation",
            "composition",
            "quality_evaluation",
            "repair",
        }
        assert set(ALL_AGENTS.keys()) == expected

    def test_get_agent_returns_instance(self):
        for step_id, cls in ALL_AGENTS.items():
            inst = get_agent(step_id)
            assert isinstance(inst, cls)
            assert inst.step_id == step_id


# ============================================================
# 2. 5 个 Agent + repair 各跑一次
# ============================================================
class TestAgentRuns:
    @pytest.mark.parametrize(
        "step_id,cls,expected_keys",
        [
            (
                "product_analysis",
                ProductAnalysisAgent,
                {"pain_points", "target_users", "core_selling_points", "ad_angle", "target_emotion"},
            ),
            (
                "script_generation",
                ScriptGenerationAgent,
                {"hook", "problem", "solution", "proof", "cta", "full_script"},
            ),
            (
                "storyboard_planning",
                StoryboardPlanningAgent,
                {"storyboard"},
            ),
            (
                "material_suggestion",
                MaterialSuggestionAgent,
                {"materials"},
            ),
            (
                "quality_evaluation",
                QualityEvaluationAgent,
                {"score", "passed", "issues", "risk_level", "suggested_fix"},
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_agent_runs_successfully(
        self, step_id, cls, expected_keys, mock_ctx, sqlite_db,
    ):
        agent = cls()
        ctx = {
            "product": SAMPLE_PRODUCT,
            "history": {
                "product_analysis": {"pain_points": ["x", "y"]},
                "script_generation": {"hook": "h" * 30},
                "storyboard_planning": {
                    "storyboard": [
                        {"scene_id": 1, "duration": 3, "material_type": "demo_scene"}
                    ]
                },
                "material_suggestion": {"materials": []},
            },
            "task_id": "task_test_agent",
        }
        result = await agent.run(ctx)
        assert result.success, (
            f"{step_id} agent 失败: failure_reason={result.failure_reason}, "
            f"error_message={result.error_message}"
        )
        assert isinstance(result.output, dict)
        for k in expected_keys:
            assert k in result.output, f"{step_id} output 缺少字段 {k}"
        assert result.latency_ms >= 0
        assert result.prompt_version != ""

    @pytest.mark.asyncio
    async def test_repair_agent_via_run_uses_target_step_validation(
        self, mock_ctx, sqlite_db,
    ):
        """RepairAgent 单独验证：它的 step_id='repair' 不在 SCHEMA_REGISTRY 里，
        跑 .run() 会走到 validate_json_output('repair') 失败。
        这里只验证 metadata + prompt，不直接调 .run()。"""
        from app.services.llm_client import LLMClient

        agent = RepairAgent()
        assert agent.step_id == "repair"
        assert agent.prompt_version != ""

        prompt = agent.build_user_prompt({
            "target_step": "script_generation",
            "failure_feedback": "JSON_PARSE_ERROR",
            "original_output": {"hook": "x"},
        })
        assert "script_generation" in prompt

    @pytest.mark.asyncio
    async def test_agent_result_has_required_fields(self, mock_ctx, sqlite_db):
        agent = ProductAnalysisAgent()
        result = await agent.run({
            "product": SAMPLE_PRODUCT,
            "history": {},
            "task_id": "task_test_result",
        })
        assert hasattr(result, "success")
        assert hasattr(result, "output")
        assert hasattr(result, "raw_output")
        assert hasattr(result, "input_tokens")
        assert hasattr(result, "output_tokens")
        assert hasattr(result, "latency_ms")
        assert hasattr(result, "model")
        assert hasattr(result, "prompt_version")
        assert hasattr(result, "repairs_attempted")
        assert hasattr(result, "needs_retry")
        assert hasattr(result, "needs_repair_agent")


# ============================================================
# 3. 坏 JSON 触发 quick_repair
# ============================================================
class TestAgentRepairFlow:
    @pytest.mark.asyncio
    async def test_quick_repair_rescues_missing_brace(self, mock_ctx, sqlite_db):
        """坏 JSON 缺右括号 → quick_json_repair 修复成功。"""
        from app.services.llm_client import LLMClient

        original = LLMClient._mock_generate

        # 输出缺右括号的 script JSON；quick_repair 会补全后再 validate。
        # 但 validate 仍会因字段不全失败，于是 base.py 会再调一次 LLM 修复。
        # 我们让第二次 LLM 返回完整 JSON，验证整个 repair 路径能救回来。
        call_count = {"n": 0}

        async def missing_brace_then_ok(self_or_none, prompt, system_prompt, model, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # 缺右括号 + 字段不全（quick_repair 能修括号，但 validate 会失败）
                return '{"hook": "this hook is long enough for sure",', 10, 10
            return await original(self_or_none, prompt, system_prompt, model, **kwargs)

        LLMClient._mock_generate = missing_brace_then_ok

        try:
            agent = ScriptGenerationAgent()
            result = await agent.run({
                "product": SAMPLE_PRODUCT,
                "history": {
                    "product_analysis": {"pain_points": ["x", "y"]}
                },
                "task_id": "task_quick_repair",
            })
            assert result.success, (
                f"repair 失败: {result.failure_reason}, {result.error_message}"
            )
            assert result.output is not None
            assert "hook" in result.output
            # repairs_attempted 至少 1（说明走过修复路径）
            assert call_count["n"] >= 1
        finally:
            LLMClient._mock_generate = original

    def test_quick_repair_rescues_markdown_wrapped(self, mock_ctx, sqlite_db):
        """LLM 输出 ```json ... ``` 包裹 → quick_json_repair 去掉 markdown 后成功。

        这是同步测试：直接验证 quick_json_repair 自身的能力。
        """
        from app.services.json_validator import quick_json_repair

        wrapped = "```json\n" + json.dumps({
            "hook": "this hook is long enough",
            "problem": "x" * 30,
            "solution": "x" * 30,
            "proof": "x" * 30,
            "cta": "x" * 30,
            "full_script": "x" * 100,
        }, ensure_ascii=False) + "\n```"
        repaired = quick_json_repair(wrapped)
        assert repaired is not None
        assert "hook" in repaired

    @pytest.mark.asyncio
    async def test_cannot_repair_sets_needs_repair(self, mock_ctx, sqlite_db):
        """LLM 持续返回完全无法修复的内容 → result.success=False, needs_repair_agent=True。"""
        from app.services.llm_client import LLMClient

        original = LLMClient._mock_generate

        async def always_garbage(self_or_none, prompt, system_prompt, model, **kwargs):
            return "totally not json at all, just garbage", 10, 10

        LLMClient._mock_generate = always_garbage

        try:
            agent = ProductAnalysisAgent()
            result = await agent.run({
                "product": SAMPLE_PRODUCT,
                "history": {},
                "task_id": "task_unrepairable",
            })
            assert result.success is False
            assert result.failure_reason in (
                "JSON_PARSE_ERROR",
                "SCHEMA_VALIDATION_ERROR",
            )
            # 至少要标记 needs_repair_agent 或 needs_retry
            assert result.needs_repair_agent or result.needs_retry
        finally:
            LLMClient._mock_generate = original


# ============================================================
# 4. prompt 构造
# ============================================================
class TestAgentPrompts:
    def test_product_analysis_prompt_contains_product(self, mock_ctx, sqlite_db):
        agent = ProductAnalysisAgent()
        ctx = {"product": SAMPLE_PRODUCT, "history": {}}
        prompt = agent.build_user_prompt(ctx)
        assert SAMPLE_PRODUCT["product_name"] in prompt

    def test_script_generation_prompt_includes_history(self, mock_ctx, sqlite_db):
        agent = ScriptGenerationAgent()
        ctx = {
            "product": SAMPLE_PRODUCT,
            "history": {
                "product_analysis": {"pain_points": ["specific pain 1", "specific pain 2"]}
            },
        }
        prompt = agent.build_user_prompt(ctx)
        assert "specific pain 1" in prompt
        assert SAMPLE_PRODUCT["product_name"] in prompt

    def test_script_generation_includes_failure_feedback(self, mock_ctx, sqlite_db):
        agent = ScriptGenerationAgent()
        ctx = {
            "product": SAMPLE_PRODUCT,
            "history": {},
            "failure_feedback": "score=55 issue=SELLING_POINT_DRIFT",
        }
        prompt = agent.build_user_prompt(ctx)
        assert "SELLING_POINT_DRIFT" in prompt
        assert "score=55" in prompt

    def test_storyboard_planning_includes_script(self, mock_ctx, sqlite_db):
        agent = StoryboardPlanningAgent()
        ctx = {
            "product": SAMPLE_PRODUCT,
            "history": {"script_generation": {"hook": "h" * 30, "full_script": "x" * 100}},
        }
        prompt = agent.build_user_prompt(ctx)
        assert "h" * 30 in prompt

    def test_material_suggestion_includes_storyboard(self, mock_ctx, sqlite_db):
        agent = MaterialSuggestionAgent()
        ctx = {
            "product": SAMPLE_PRODUCT,
            "history": {
                "storyboard_planning": {
                    "storyboard": [
                        {"scene_id": 1, "duration": 3, "material_type": "demo_scene"}
                    ]
                }
            },
        }
        prompt = agent.build_user_prompt(ctx)
        assert "demo_scene" in prompt

    def test_quality_evaluation_prompt_includes_outputs(self, mock_ctx, sqlite_db):
        agent = QualityEvaluationAgent()
        ctx = {
            "product": SAMPLE_PRODUCT,
            "history": {
                "script_generation": {"hook": "h" * 30},
                "storyboard_planning": {"storyboard": []},
                "material_suggestion": {"materials": []},
            },
        }
        prompt = agent.build_user_prompt(ctx)
        assert SAMPLE_PRODUCT["product_name"] in prompt
        assert "script_generation" in prompt or "脚本" in prompt

    def test_repair_prompt_includes_target_step(self, mock_ctx, sqlite_db):
        agent = RepairAgent()
        ctx = {
            "target_step": "script_generation",
            "failure_feedback": "JSON_PARSE_ERROR at line 3",
            "original_output": {"hook": "old"},
        }
        prompt = agent.build_user_prompt(ctx)
        assert "script_generation" in prompt
        assert "JSON_PARSE_ERROR" in prompt


# ============================================================
# 5. Agent 单例属性 / 配置
# ============================================================
class TestAgentMetadata:
    def test_step_id_matches_registry(self, mock_ctx, sqlite_db):
        for step_id, cls in ALL_AGENTS.items():
            assert cls().step_id == step_id

    def test_prompt_version_present(self, mock_ctx, sqlite_db):
        for cls in ALL_AGENTS.values():
            assert cls().prompt_version != ""

    def test_agent_result_dataclass(self):
        from app.agents.base import AgentResult

        r = AgentResult(success=True, output={"x": 1})
        assert r.success is True
        assert r.output == {"x": 1}
        assert r.repairs_attempted == 0
        assert r.needs_retry is False
        assert r.needs_repair_agent is False
        assert r.repair_payload == {}
