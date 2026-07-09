"""每个 Agent 的 JSON Schema - 用于结构化输出校验 + 失败反馈"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class ProductAnalysisSchema(BaseModel):
    """商品理解 Agent 输出 Schema"""

    pain_points: List[str] = Field(min_length=2, max_length=5, description="用户痛点")
    target_users: List[str] = Field(min_length=1, max_length=5, description="目标人群")
    core_selling_points: List[str] = Field(min_length=2, max_length=5, description="核心卖点")
    ad_angle: str = Field(min_length=4, description="广告切入角度")
    target_emotion: str = Field(description="目标情绪，比如 relief / excitement / security")


class ScriptSchema(BaseModel):
    """广告脚本 Agent 输出"""

    hook: str = Field(min_length=10, max_length=80, description="前 3 秒钩子")
    problem: str = Field(min_length=10, max_length=120, description="痛点放大")
    solution: str = Field(min_length=10, max_length=120, description="产品解决方案")
    proof: str = Field(min_length=10, max_length=120, description="信任增强 / 用户证言")
    cta: str = Field(min_length=5, max_length=60, description="行动号召")
    full_script: str = Field(min_length=80, max_length=400, description="完整连贯脚本")


class StoryboardSceneSchema(BaseModel):
    """单个分镜"""

    scene_id: int = Field(ge=1, le=10)
    duration: int = Field(ge=1, le=8)
    visual: str = Field(min_length=10, description="画面描述")
    subtitle: str = Field(min_length=5, description="字幕文案")
    voiceover: str = Field(min_length=5, description="配音文案")
    camera_shot: str = Field(description="镜头：close-up / wide / medium / pan / cut")
    material_type: str = Field(description="pain_point_scene / demo_scene / proof_scene / cta_scene")


class StoryboardSchema(BaseModel):
    """分镜规划"""

    storyboard: List[StoryboardSceneSchema] = Field(min_length=3, max_length=8)


class MaterialItemSchema(BaseModel):
    """素材建议 - 单镜头"""

    scene_id: int
    material_keyword: str
    material_type: str
    source: str = "mock_library"
    description: Optional[str] = None


class MaterialSuggestionSchema(BaseModel):
    materials: List[MaterialItemSchema]


class EvaluationIssueSchema(BaseModel):
    type: str  # SELLING_POINT_DRIFT / STORYBOARD_MISSING / ...
    detail: str


class EvaluationSchema(BaseModel):
    """LLM-as-Judge 输出"""

    score: int = Field(ge=0, le=100)
    passed: bool
    issues: List[EvaluationIssueSchema] = Field(default_factory=list)
    risk_level: str = Field(description="low / medium / high")
    suggested_fix: str = Field(default="")


# ============================================================
# Helper - Pydantic Schema → JSON Schema (给 LLM 当 prompt 参数)
# ============================================================
def pydantic_to_json_schema(pydantic_cls) -> Dict[str, Any]:
    """Pydantic v2 model → 用于 prompt 的 JSON schema 描述"""
    return pydantic_cls.model_json_schema()
