"""Agent 5: 质量评估 - LLM-as-Judge
评估 6 维度：卖点一致性 / 平台适配 / 分镜完整 / 时长合规 / 风险控制 / JSON 格式
"""
import json
from app.agents.base import BaseAgent
from app.schemas.agent_schemas import EvaluationSchema, pydantic_to_json_schema


class QualityEvaluationAgent(BaseAgent):
    step_id = "quality_evaluation"
    prompt_version = "v1.0"

    def build_system_prompt(self) -> str:
        return (
            "你是一名广告审核员，从用户角度评估短视频脚本是否符合投放标准。"
            "你需要严格、结构化地输出评估结果。"
        )

    def build_user_prompt(self, ctx: dict) -> str:
        product = ctx.get("product", {})
        history = ctx.get("history", {})

        schema = pydantic_to_json_schema(EvaluationSchema)

        scoring_dimensions = """
        评分维度 (总分 100):
        1. 卖点一致性 (selling_point_consistency, 0-25 分):
           - 是否围绕商品 selling_points 展开
           - 是否出现卖点偏移
        2. 平台适配 (platform_fit, 0-15 分):
           - 是否适合产品 target_platform 的风格
           - hook / 节奏 / 镜头是否到位
        3. 分镜完整性 (storyboard_completeness, 0-20 分):
           - storyboard 是否 ≥ 3 个镜头
           - 镜头时长总和是否在合理范围
           - 是否缺失关键画面
        4. 时长合规 (duration_fit, 0-15 分):
           - 是否在产品要求时长内 (如 15 秒)
           - 有无脚本过长/过短
        5. 风险控制 (risk_control, 0-15 分):
           - 是否存在夸大宣传
           - 是否符合广告法
           - 是否有不当用词
        6. 输出格式 (output_format, 0-10 分):
           - JSON 是否合法
           - 必填字段是否完整
        """

        return (
            "请评估下面这条广告的执行结果，给出 0-100 评分与详细问题列表。\n\n"
            f"原始商品信息:\n{json.dumps(product, ensure_ascii=False, indent=2)}\n\n"
            f"脚本输出:\n{json.dumps(history.get('script_generation', {}), ensure_ascii=False, indent=2)}\n\n"
            f"分镜输出:\n{json.dumps(history.get('storyboard_planning', {}), ensure_ascii=False, indent=2)}\n\n"
            f"素材输出:\n{json.dumps(history.get('material_suggestion', {}), ensure_ascii=False, indent=2)}\n\n"
            f"{scoring_dimensions}\n"
            f"输出 Schema:\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
            "要求:\n"
            "1. score 必须是 0-100 整数；\n"
            "2. passed = (score >= 70) AND (risk_level != 'high')；\n"
            "3. issues 数组列出所有问题，每条 issue 的 type 字段必须是:\n"
            "   - SELLING_POINT_DRIFT\n"
            "   - STORYBOARD_MISSING\n"
            "   - CONTENT_TOO_LONG\n"
            "   - JSON_PARSE_ERROR\n"
            "   - SCHEMA_VALIDATION_ERROR\n"
            "   - PLATFORM_MISMATCH\n"
            "   - RISKY_CLAIM\n"
            "   中的一种；\n"
            "4. suggested_fix 给具体修复指令（如果 passed=true 可留空字符串）；\n"
            "5. 只输出 JSON。\n"
            "请直接输出 JSON:"
        )
