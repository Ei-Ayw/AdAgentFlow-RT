"""Agent 1: 商品理解 - 从商品信息中提取痛点 / 目标用户 / 核心卖点
"""
import json
from app.agents.base import BaseAgent
from app.schemas.agent_schemas import ProductAnalysisSchema, pydantic_to_json_schema


class ProductAnalysisAgent(BaseAgent):
    step_id = "product_analysis"
    prompt_version = "v1.1"

    def build_system_prompt(self) -> str:
        return (
            "你是一名资深电商广告策划，擅长从商品信息中提炼广告切入点。"
            "你必须严格按要求输出 JSON，禁止解释。"
        )

    def build_user_prompt(self, ctx: dict) -> str:
        product = ctx.get("product", {})
        schema = pydantic_to_json_schema(ProductAnalysisSchema)
        return (
            "请基于以下商品信息，输出 JSON 描述广告切入角度。\n\n"
            f"商品信息:\n{json.dumps(product, ensure_ascii=False, indent=2)}\n\n"
            f"输出 Schema:\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
            "要求:\n"
            "1. pain_points 必须覆盖用户真实困扰，至少 2 条；\n"
            "2. core_selling_points 必须从商品 selling_points 中提炼核心，最多 3-5 条；\n"
            "3. ad_angle 必须有差异化、具体可执行；\n"
            "4. target_emotion 用 1-2 个英文单词描述情绪方向；\n"
            "5. 只输出 JSON，无任何解释或 markdown 标记。\n"
            "请直接输出 JSON:"
        )
