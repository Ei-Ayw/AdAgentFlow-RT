"""Agent 2: 广告脚本 - 生成 15 秒短视频脚本
"""
import json
from app.agents.base import BaseAgent
from app.schemas.agent_schemas import ScriptSchema, pydantic_to_json_schema


class ScriptGenerationAgent(BaseAgent):
    step_id = "script_generation"
    prompt_version = "v1.2"

    def build_system_prompt(self) -> str:
        return (
            "你是 5 年经验的 TikTok 爆款广告脚本写手，写过 100+ 跑量素材。"
            "你的脚本特点是：前 3 秒必抓人，痛点具体可信，CTA 明确。"
            "严格按要求输出 JSON，禁止解释。"
        )

    def build_user_prompt(self, ctx: dict) -> str:
        product = ctx.get("product", {})
        product_analysis = ctx.get("history", {}).get("product_analysis", {})
        failure_feedback = ctx.get("failure_feedback", "")
        platform = product.get("platform", "TikTok")
        duration = product.get("duration", 15)

        schema = pydantic_to_json_schema(ScriptSchema)

        base = (
            f"请基于以下商品信息生成一段 {duration} 秒短视频带货脚本。\n\n"
            f"商品信息:\n{json.dumps(product, ensure_ascii=False, indent=2)}\n\n"
            f"卖点分析:\n{json.dumps(product_analysis, ensure_ascii=False, indent=2)}\n\n"
            f"目标平台: {platform}, 总时长: {duration} 秒\n\n"
            f"输出 Schema:\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
            "要求:\n"
            "1. hook 必须能在 3 秒内抓住注意力，使用反问 / 痛点提问 / 惊人数据；\n"
            "2. problem 必须具体，描述用户使用场景和情绪；\n"
            "3. solution 必须把核心卖点融进具体画面；\n"
            "4. proof 要给出信任增强（用户数、评价、销量、奖项等）；\n"
            "5. cta 必须明确指令式（点击 / 立刻 / 立即 / 下单 等动词开头）；\n"
            "6. full_script 串联 5 段，全长不超过 80 个中文字符每秒；\n"
            "7. 严格符合 JSON Schema；\n"
            "8. 只输出 JSON。\n"
        )
        if failure_feedback:
            base += (
                f"\n\n上次评估反馈（必须修正）:\n{failure_feedback}\n"
            )
        base += "\n请直接输出 JSON:"
        return base
