"""Agent 3: 分镜规划 - 把脚本拆成镜头
"""
import json
from app.agents.base import BaseAgent
from app.schemas.agent_schemas import StoryboardSchema, pydantic_to_json_schema


class StoryboardPlanningAgent(BaseAgent):
    step_id = "storyboard_planning"
    prompt_version = "v1.1"

    def build_system_prompt(self) -> str:
        return (
            "你是广告分镜导演，熟悉短视频拍摄节奏与镜头语言。"
            "严格按 Schema 输出 JSON。"
        )

    def build_user_prompt(self, ctx: dict) -> str:
        product = ctx.get("product", {})
        script = ctx.get("history", {}).get("script_generation", {})
        duration = product.get("duration", 15)

        schema = pydantic_to_json_schema(StoryboardSchema)

        return (
            f"请把以下脚本拆分为适配 {duration} 秒短视频的分镜表。\n\n"
            f"脚本:\n{json.dumps(script, ensure_ascii=False, indent=2)}\n\n"
            f"输出 Schema:\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
            "要求:\n"
            "1. storyboard 数量 3-8 个；\n"
            "2. 每个 scene 时长 (duration) 之和 ≤ 总时长 +2 秒；\n"
            "3. material_type 必须覆盖 pain_point_scene / demo_scene / proof_scene / cta_scene 中的至少 3 种；\n"
            "4. 镜头语言使用 cinematic 词汇（close-up / wide / pan / cut / medium / over-the-shoulder）；\n"
            "5. visual 描述具体可拍摄的画面，不要抽象（如 '白领戴上风扇吹起头发' 而非 '展示产品'）；\n"
            "6. subtitle 不超过 18 个字符；\n"
            "7. 只输出 JSON。\n"
            "请直接输出 JSON:"
        )
