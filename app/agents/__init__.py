"""统一 Agent 入口"""
from app.agents.product_analysis_agent import ProductAnalysisAgent
from app.agents.script_agent import ScriptGenerationAgent
from app.agents.storyboard_agent import StoryboardPlanningAgent
from app.agents.material_agent import MaterialSuggestionAgent
from app.agents.evaluation_agent import QualityEvaluationAgent
from app.agents.repair_agent import RepairAgent

ALL_AGENTS = {
    "product_analysis": ProductAnalysisAgent,
    "script_generation": ScriptGenerationAgent,
    "storyboard_planning": StoryboardPlanningAgent,
    "material_suggestion": MaterialSuggestionAgent,
    "quality_evaluation": QualityEvaluationAgent,
    "repair": RepairAgent,
}


def get_agent(step_id: str):
    return ALL_AGENTS[step_id]()
