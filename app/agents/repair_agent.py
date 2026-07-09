"""Agent 6: 失败修复 - 根据评估反馈做局部重写
不修改原 step，而是基于反馈重新生成
"""
import json
from app.agents.base import BaseAgent
from app.schemas.agent_schemas import pydantic_to_json_schema
from app.core.failure_codes import FailureReason


class RepairAgent(BaseAgent):
    step_id = "repair"
    prompt_version = "v1.0"

    def build_system_prompt(self) -> str:
        return (
            "你是一名资深的修复工程师，根据下游评估反馈，定向修复上游输出。"
            "只输出修复后的 JSON，禁止解释。"
        )

    def build_user_prompt(self, ctx: dict) -> str:
        target_step = ctx.get("target_step", "")
        failure_feedback = ctx.get("failure_feedback", "")
        original_output = ctx.get("original_output", {})

        # 根据目标 step 选 schema
        schema_map = {
            "product_analysis": ("product_analysis", pydantic_to_json_schema(__import__("app.schemas.agent_schemas", fromlist=["ProductAnalysisSchema"]).ProductAnalysisSchema)),
            "script_generation": ("script_generation", pydantic_to_json_schema(__import__("app.schemas.agent_schemas", fromlist=["ScriptSchema"]).ScriptSchema)),
            "storyboard_planning": ("storyboard_planning", pydantic_to_json_schema(__import__("app.schemas.agent_schemas", fromlist=["StoryboardSchema"]).StoryboardSchema)),
            "material_suggestion": ("material_suggestion", pydantic_to_json_schema(__import__("app.schemas.agent_schemas", fromlist=["MaterialSuggestionSchema"]).MaterialSuggestionSchema)),
        }
        schema_name, schema = schema_map.get(target_step, ("product_analysis", "{}"))

        return (
            f"目标 step: {target_step}\n\n"
            f"失败反馈:\n{failure_feedback}\n\n"
            f"原始输出:\n{json.dumps(original_output, ensure_ascii=False, indent=2)}\n\n"
            f"目标 Schema:\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
            "要求:\n"
            "1. 根据失败反馈做定向修复，不要随便重写；\n"
            "2. 保持原始输出中可用的部分；\n"
            "3. 严格符合 Schema；\n"
            "4. 只输出 JSON。\n"
            "请直接输出 JSON:"
        )
