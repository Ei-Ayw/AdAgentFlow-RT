"""LLM 客户端 - 适配 anthropic 协议 + 内置 mock 兜底

生产用 minimax (兼容 anthropic 协议)，开发用 mock
"""
import json
import time
import random
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger()


@dataclass
class LLMResponse:
    """统一的 LLM 返回结构"""

    content: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    model: str
    prompt_version: str = "v1.0"


class LLMError(Exception):
    """LLM 业务异常基类"""

    def __init__(self, message: str, error_type: str = "unknown", retryable: bool = True):
        super().__init__(message)
        self.error_type = error_type
        self.retryable = retryable


class LLMTimeoutError(LLMError):
    """超时"""

    def __init__(self, message: str = "LLM timeout"):
        super().__init__(message, error_type="MODEL_TIMEOUT", retryable=True)


class LLMJsonError(LLMError):
    """JSON 解析失败"""

    def __init__(self, message: str = "JSON parse failed"):
        super().__init__(message, error_type="JSON_PARSE_ERROR", retryable=True)


class LLMClient:
    """统一的 LLM 客户端 - mock / real 自动切换

    设计要点：
    1. mock 模式下不联网，本地模板生成；
    2. real 模式下走 anthropic 兼容协议；
    3. 统一返回 LLMResponse，便于上层统计 token / latency。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        use_mock: Optional[bool] = None,
    ):
        self.api_key = api_key or settings.anthropic_auth_token
        self.base_url = base_url or settings.anthropic_base_url
        self.use_mock = (
            use_mock if use_mock is not None else (settings.use_mock_llm or not self.api_key)
        )
        self.timeout = settings.llm_timeout
        self.model = settings.anthropic_default_haiku_model

    # ================================================================
    # Public API
    # ================================================================
    async def generate_json(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        prompt_version: str = "v1.0",
        step_id: Optional[str] = None,
    ) -> tuple[Any, LLMResponse]:
        """生成 JSON - 返回 (parsed_dict, LLMResponse)

        Raises:
            LLMTimeoutError: 超时
            LLMJsonError: 输出不是合法 JSON
        """
        model = model or self.model
        start = time.time()
        if self.use_mock:
            content, in_tok, out_tok = await self._mock_generate(
                prompt, system_prompt, model, step_id=step_id,
            )
        else:
            content, in_tok, out_tok = await self._real_generate(
                prompt, system_prompt, model, temperature, max_tokens
            )

        latency = int((time.time() - start) * 1000)
        llm_resp = LLMResponse(
            content=content,
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_ms=latency,
            model=model,
            prompt_version=prompt_version,
        )

        # 尝试解析 JSON
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMJsonError(f"LLM 输出不是合法 JSON: {e}; content[:200]={content[:200]}")

        return parsed, llm_resp

    async def generate_text(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        model: Optional[str] = None,
        temperature: float = 0.5,
        max_tokens: int = 2048,
        prompt_version: str = "v1.0",
        step_id: Optional[str] = None,
    ) -> LLMResponse:
        """生成普通文本 - 不强求 JSON"""
        model = model or self.model
        start = time.time()
        if self.use_mock:
            content, in_tok, out_tok = "mock content", 10, 20
        else:
            content, in_tok, out_tok = await self._real_generate(
                prompt, system_prompt, model, temperature, max_tokens
            )
        latency = int((time.time() - start) * 1000)
        return LLMResponse(
            content=content,
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_ms=latency,
            model=model,
            prompt_version=prompt_version,
        )

    # ================================================================
    # Real API
    # ================================================================
    async def _real_generate(
        self,
        prompt: str,
        system_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, int, int]:
        """anthropic 协议兼容实现"""
        url = f"{self.base_url.rstrip('/')}/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "authorization": f"Bearer {self.api_key}",
        }
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            body["system"] = system_prompt

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, headers=headers, json=body)
        except httpx.TimeoutException as e:
            raise LLMTimeoutError(f"LLM 网络超时: {e}")
        except httpx.HTTPError as e:
            raise LLMError(f"LLM 网络错误: {e}", error_type="NETWORK_ERROR", retryable=True)

        if resp.status_code >= 500:
            raise LLMTimeoutError(f"LLM 服务端错误: {resp.status_code} {resp.text[:200]}")
        if resp.status_code == 401 or resp.status_code == 403:
            raise LLMError(f"鉴权失败: {resp.text}", error_type="AUTH_ERROR", retryable=False)
        if resp.status_code >= 400:
            raise LLMError(
                f"LLM 请求错误: {resp.status_code} {resp.text[:200]}",
                error_type="BAD_REQUEST",
                retryable=False,
            )

        data = resp.json()
        # anthropic 协议 content 是 list
        content = ""
        for c in data.get("content", []):
            if c.get("type") == "text":
                content = c.get("text", "")
                break
        in_tok = data.get("usage", {}).get("input_tokens", 0)
        out_tok = data.get("usage", {}).get("output_tokens", 0)
        return content, in_tok, out_tok

    # ================================================================
    # Mock - 模拟 Agent 输出
    # ================================================================
    async def _mock_generate(
        self,
        prompt: str,
        system_prompt: str,
        model: str,
        step_id: Optional[str] = None,
    ) -> tuple[str, int, int]:
        """根据 step_id 或 prompt 关键词决定 mock 内容

        优先使用 step_id（如果上游传了）；否则用关键词兜底
        """
        await _fake_async()

        # 1. 优先 step_id 路由
        if step_id and step_id in self.MOCK_BY_STEP:
            content = json.dumps(self.MOCK_BY_STEP[step_id], ensure_ascii=False)
        else:
            # 2. 关键词兜底（兜底场景：repair / 未知 step）
            p = prompt.lower()
            if "修复" in p or "repair" in p.lower() or "根据失败反馈" in p:
                # repair 默认输出 product_analysis 风格（结构更通用）
                content = json.dumps(MOCK_PRODUCT_ANALYSIS, ensure_ascii=False)
            elif "camera_shot" in p or ("scene_id" in p and "storyboard" in p and "material_keyword" not in p):
                content = json.dumps(MOCK_STORYBOARD, ensure_ascii=False)
            elif "material_keyword" in p or "mock_library" in p:
                content = json.dumps(MOCK_MATERIALS, ensure_ascii=False)
            elif "full_script" in p or ("hook" in p and "cta" in p and "storyboard" not in p):
                content = json.dumps(MOCK_SCRIPT, ensure_ascii=False)
            elif "suggested_fix" in p or ("score" in p and "passed" in p):
                content = json.dumps(MOCK_EVALUATION, ensure_ascii=False)
            else:
                content = json.dumps(MOCK_PRODUCT_ANALYSIS, ensure_ascii=False)

        # 模拟 token 数
        in_tok = max(len(prompt) // 4, 50)
        out_tok = max(len(content) // 4, 50)
        return content, in_tok, out_tok

    # 默认 mock 路由（按 step_id 选择样例）
    MOCK_BY_STEP = None  # 在文件尾部构造


async def _fake_async():
    """模拟网络延迟，让压测更接近真实场景"""
    import asyncio

    await asyncio.sleep(0.05)


async def _fake_async():
    """模拟网络延迟，让压测更接近真实场景"""
    await _sleep_ms(random.randint(50, 200))


async def _sleep_ms(ms: int):
    import asyncio

    await asyncio.sleep(ms / 1000)


# ============================================================
# Mock 数据样本
# ============================================================
MOCK_PRODUCT_ANALYSIS = {
    "pain_points": [
        "出门一晒就出汗，地铁通勤粘腻不适",
        "户外作业久站闷热难耐，影响效率",
        "传统手持风扇手酸，腾不出手干活",
    ],
    "target_users": [
        "城市通勤人群",
        "外卖 / 快递户外工作者",
        "暑期亲子外出家庭",
    ],
    "core_selling_points": [
        "无叶挂颈双手解放",
        "6 小时超长续航",
        "仅 180g 轻盈无感佩戴",
        "三档风量声控档位",
    ],
    "ad_angle": "通勤酷暑 vs 挂颈清凉对比 - 借势夏日高频场景",
    "target_emotion": "relief + confidence",
}

MOCK_SCRIPT = {
    "hook": "这条 38 度的高温天里，你还在汗如雨下？",
    "problem": (
        "地铁里、办公室、外卖路上，传统风扇要么手持累，要么噪音让人崩溃，"
        "撑不到你下班回家。"
    ),
    "solution": (
        "便携挂颈无叶风扇，挂在脖子上秒变私人气候站。三档风量，"
        "6 小时续航一整天通勤无忧。"
    ),
    "proof": (
        "180 克无感重量，比耳机还轻；52 分贝低噪音，开会也能用。"
        "已经陪伴 50 万 + 户外工作者度过夏天。"
    ),
    "cta": "点击橱窗，立刻下单，今天就降温！",
    "full_script": (
        "这条 38 度的高温天里，你还在汗如雨下？"
        "地铁里、办公室、外卖路上，传统风扇要么手持累，要么噪音让人崩溃，"
        "撑不到你下班回家。便携挂颈无叶风扇，挂在脖子上秒变私人气候站。"
        "三档风量，6 小时续航一整天通勤无忧。"
        "180 克无感重量，比耳机还轻；52 分贝低噪音，开会也能用。"
        "已经陪伴 50 万 + 户外工作者度过夏天。"
        "点击橱窗，立刻下单，今天就降温！"
    ),
}

MOCK_STORYBOARD = {
    "storyboard": [
        {
            "scene_id": 1,
            "duration": 3,
            "visual": "通勤白领在地铁里满头大汗，狼狈地边走边用文件扇风",
            "subtitle": "38°C 高温 通勤崩溃现场",
            "voiceover": "这条 38 度的高温天里，你还在汗如雨下？",
            "camera_shot": "medium",
            "material_type": "pain_point_scene",
        },
        {
            "scene_id": 2,
            "duration": 3,
            "visual": "特写主角戴上挂颈风扇，立刻清爽表情变化，吹动头发动画",
            "subtitle": "一秒入秋 清凉上线",
            "voiceover": "便携挂颈无叶风扇，挂在脖子上秒变私人气候站。",
            "camera_shot": "close-up",
            "material_type": "demo_scene",
        },
        {
            "scene_id": 3,
            "duration": 3,
            "visual": "外卖小哥边骑车边戴风扇跑单，全程凉爽对照传统工人汗流浃背",
            "subtitle": "6 小时续航 一整天通勤无忧",
            "voiceover": "三档风量，6 小时续航一整天通勤无忧。",
            "camera_shot": "wide",
            "material_type": "proof_scene",
        },
        {
            "scene_id": 4,
            "duration": 3,
            "visual": "用户特写 + 评分 + 用户好评弹窗",
            "subtitle": "50 万 + 用户的共同选择",
            "voiceover": "已经陪伴 50 万 + 户外工作者度过夏天。",
            "camera_shot": "close-up",
            "material_type": "proof_scene",
        },
        {
            "scene_id": 5,
            "duration": 3,
            "visual": "产品 hero shot + 醒目价格 + 立即购买按钮动画",
            "subtitle": "立即下单 今天就降温",
            "voiceover": "点击橱窗，立刻下单，今天就降温！",
            "camera_shot": "cut",
            "material_type": "cta_scene",
        },
    ]
}

MOCK_MATERIALS = {
    "materials": [
        {
            "scene_id": 1,
            "material_keyword": "sweating commuter subway",
            "material_type": "pain_point_scene",
            "source": "mock_library",
            "description": "通勤人群地铁车厢出汗特写 8 秒素材",
        },
        {
            "scene_id": 2,
            "material_keyword": "neck fan unboxing happy",
            "material_type": "demo_scene",
            "source": "mock_library",
            "description": "白领拆开挂颈风扇佩戴露出笑容 6 秒",
        },
        {
            "scene_id": 3,
            "material_keyword": "delivery rider cooling",
            "material_type": "proof_scene",
            "source": "mock_library",
            "description": "外卖骑手戴风扇路上配送片段 10 秒",
        },
        {
            "scene_id": 4,
            "material_keyword": "user testimonial 5 star",
            "material_type": "proof_scene",
            "source": "mock_library",
            "description": "用户 5 星好评弹窗滚动特效",
        },
        {
            "scene_id": 5,
            "material_keyword": "product hero shot cta",
            "material_type": "cta_scene",
            "source": "mock_library",
            "description": "产品 hero 镜头 + 价格 + 立即购买按钮动画",
        },
    ]
}

MOCK_EVALUATION = {
    "score": 87,
    "passed": True,
    "issues": [],
    "risk_level": "low",
    "suggested_fix": "",
}


# ============================================================
# Mock 路由表 - 在所有 MOCK_* 定义后绑定
# ============================================================
LLMClient.MOCK_BY_STEP = {
    "product_analysis": MOCK_PRODUCT_ANALYSIS,
    "script_generation": MOCK_SCRIPT,
    "storyboard_planning": MOCK_STORYBOARD,
    "material_suggestion": MOCK_MATERIALS,
    "quality_evaluation": MOCK_EVALUATION,
}


# Singleton
_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
