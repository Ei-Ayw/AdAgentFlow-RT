"""JSON Schema 校验 + 自动修复 Prompt 构造器"""
import json
from typing import Any, Dict, Optional, Tuple
from pydantic import ValidationError
import jsonschema
from jsonschema import Draft7Validator

from app.schemas.agent_schemas import (
    ProductAnalysisSchema,
    ScriptSchema,
    StoryboardSchema,
    MaterialSuggestionSchema,
    EvaluationSchema,
)


SCHEMA_REGISTRY = {
    "product_analysis": (ProductAnalysisSchema, ProductAnalysisSchema.model_json_schema()),
    "script_generation": (ScriptSchema, ScriptSchema.model_json_schema()),
    "storyboard_planning": (StoryboardSchema, StoryboardSchema.model_json_schema()),
    "material_suggestion": (MaterialSuggestionSchema, MaterialSuggestionSchema.model_json_schema()),
    "quality_evaluation": (EvaluationSchema, EvaluationSchema.model_json_schema()),
}


class JsonValidationError(Exception):
    """JSON 校验失败 - 携带详细原因便于修复"""

    def __init__(
        self,
        message: str,
        schema_name: str,
        raw_content: str,
        error_details: list,
        error_type: str = "SCHEMA_VALIDATION_ERROR",
    ):
        super().__init__(message)
        self.schema_name = schema_name
        self.raw_content = raw_content
        self.error_details = error_details
        self.error_type = error_type


def validate_json_output(
    schema_name: str,
    content: str,
) -> Tuple[Any, str]:
    """统一入口 - 两层校验

    1. JSON 解析 (catch JSONDecodeError)
    2. Pydantic 模型校验 (catch ValidationError)
    3. jsonschema 兜底

    Returns:
        (parsed_dict, canonical_json_str)

    Raises:
        JsonValidationError
    """
    pyd_cls, js_schema = SCHEMA_REGISTRY.get(schema_name, (None, None))
    if pyd_cls is None:
        raise JsonValidationError(
            message=f"未知 schema: {schema_name}",
            schema_name=schema_name,
            raw_content=content,
            error_details=[f"schema_name={schema_name} 未注册"],
        )

    # 第 1 层：JSON 解析
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        raise JsonValidationError(
            message=f"JSON 解析失败: {e}",
            schema_name=schema_name,
            raw_content=content,
            error_details=[f"line={e.lineno}, col={e.colno}, msg={e.msg}"],
            error_type="JSON_PARSE_ERROR",
        )

    # 第 2 层：Pydantic 校验
    try:
        instance = pyd_cls.model_validate(parsed)
    except ValidationError as e:
        details = []
        for err in e.errors():
            details.append(
                f"loc={'/'.join(str(x) for x in err['loc'])}: {err['msg']}"
            )
        raise JsonValidationError(
            message=f"Schema 校验失败",
            schema_name=schema_name,
            raw_content=content,
            error_details=details,
        )

    import json as _json

    canonical = _json.dumps(instance.model_dump(), ensure_ascii=False)
    return instance.model_dump(), canonical


def build_repair_prompt(
    schema_name: str,
    raw_content: str,
    error_details: list,
    original_system: str = "",
) -> str:
    """根据校验错误构造修复 Prompt

    关键：把错误信息 + 原始输出返回给 LLM，让它有针对性地修
    """
    _, js_schema = SCHEMA_REGISTRY[schema_name]
    schema_desc = json.dumps(js_schema, ensure_ascii=False, indent=2)
    err_text = "\n".join(f"- {d}" for d in error_details)
    return (
        "你刚才生成的 JSON 不符合目标 Schema，校验失败。"
        f"\nSchema: {schema_name}\n\n"
        f"目标 Schema (JSON Schema 7.0):\n{schema_desc}\n\n"
        f"你上一次的输出:\n{raw_content}\n\n"
        f"校验错误列表:\n{err_text}\n\n"
        "要求:\n"
        "1. 只返回 JSON 内容，不要任何 markdown、解释或前后缀；\n"
        "2. 严格遵循上述 Schema 的字段名、类型与约束；\n"
        "3. 修复所有被指出的错误，不要新增未定义的字段。\n"
        "请直接输出合法 JSON:"
    )


def quick_json_repair(content: str) -> Optional[Any]:
    """轻量级本地 JSON 修复 - 不靠 LLM

    处理：
    - 截断的字符串
    - 缺失右括号
    - markdown 代码块包裹
    """
    s = content.strip()
    # 去掉 markdown ```json ... ```
    if s.startswith("```"):
        lines = s.split("\n")
        s = "\n".join(lines[1:])
        if s.endswith("```"):
            s = s[:-3]
    s = s.strip()
    try:
        return json.loads(s)
    except Exception:
        pass

    # 粗暴补全 - 通常用于 LLM 输出末尾缺括号
    if s.startswith("{") and not s.endswith("}"):
        s2 = s
        # 补全缺失的右括号
        opens = s2.count("{")
        closes = s2.count("}")
        s2 += "}" * (opens - closes)
        try:
            return json.loads(s2)
        except Exception:
            pass

    if s.startswith("[") and not s.endswith("]"):
        s2 = s
        opens = s2.count("[")
        closes = s2.count("]")
        s2 += "]" * (opens - closes)
        try:
            return json.loads(s2)
        except Exception:
            return None

    return None
