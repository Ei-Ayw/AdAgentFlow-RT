"""Agent 4: 素材建议 - 给每个镜头匹配素材建议

不连真实视频生成，输出 mock 素材库匹配结果
"""
import json
from app.agents.base import BaseAgent
from app.schemas.agent_schemas import MaterialSuggestionSchema, pydantic_to_json_schema


class MaterialSuggestionAgent(BaseAgent):
    step_id = "material_suggestion"
    prompt_version = "v1.0"

    def build_system_prompt(self) -> str:
        return (
            "你是短视频素材采购，熟悉国内外素材库（千图、千库、Pexels 等）。"
            "严格按 Schema 输出 JSON。"
        )

    def build_user_prompt(self, ctx: dict) -> str:
        storyboard = ctx.get("history", {}).get("storyboard_planning", {}).get("storyboard", [])

        schema = pydantic_to_json_schema(MaterialSuggestionSchema)

        return (
            "请为以下分镜表的每个镜头推荐素材。\n\n"
            f"分镜表:\n{json.dumps({'storyboard': storyboard}, ensure_ascii=False, indent=2)}\n\n"
            f"输出 Schema:\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
            "要求:\n"
            "1. materials 数组长度 = storyboard 数组长度；\n"
            "2. 每个 scene_id 必须与 storyboard 一一对应；\n"
            "3. material_keyword 必须给出可以直接搜库的英文关键词；\n"
            "4. material_type 与 storyboard 的 material_type 一致；\n"
            "5. source 写 'mock_library' 即可，未来可对接真实 API；\n"
            "6. description 简明描述理想素材的样子；\n"
            "7. 只输出 JSON。\n"
            "请直接输出 JSON:"
        )
