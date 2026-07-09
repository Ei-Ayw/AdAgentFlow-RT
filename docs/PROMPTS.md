# AdAgentFlow Prompt 版本化记录

> 本文档记录 6 个 Agent 的 Prompt 设计原则、版本演进、A/B 测试方法。Prompt 版本存储在每个 Agent 类的 `prompt_version` 字段，并写入 `task_steps.prompt_version` / `task_traces.prompt_version`。

---

## 1. Prompt 设计原则

### 1.1 通用原则

1. **Role + Task + Schema + Examples + Output format** 五段式
2. **强制 JSON 输出**：system prompt 明确"只输出 JSON，禁止解释"
3. **Schema 内嵌**：把 Pydantic 生成的 JSON Schema 直接放进 user prompt，让 LLM 知道要输出什么形状
4. **失败反馈可重试**：每次重试带上 `failure_feedback`（上次校验错误 + 原始输出），实现"定向修复"而非盲目重跑
5. **版本可追溯**：每次 prompt 变更 bump 小版本（v1.0 → v1.1），写到数据库便于 A/B 对比

### 1.2 Prompt 模板结构

```
System: 你是一名 [角色定位]，[经验描述]，[输出约束]
User: 
  请基于以下 [输入]，[任务]，[目标]。
  
  [输入数据]: {json}
  
  [可选] 上次失败反馈: {feedback}
  
  [可选] 目标 Schema: {json_schema}
  
  要求:
  1. [约束 1]
  2. [约束 2]
  ...
  N. [约束 N]
  只输出 JSON，无 markdown 标记。
  请直接输出 JSON:
```

### 1.3 版本管理约定

| 版本号 | 含义 |
|--------|------|
| v1.0 | 初始版本 |
| v1.1 | 优化约束（如增加 "镜头时长 ≤ 8 秒"） |
| v1.2 | 调整评分维度权重 |
| v1.0.repair | 自动 repair prompt 版本（LLM 介入修复时用） |

---

## 2. 各 Agent Prompt 模板

### 2.1 Agent 1：商品理解 (product_analysis, v1.1)

**角色**：资深电商广告策划

**System Prompt**：

```
你是一名资深电商广告策划，擅长从商品信息中提炼广告切入点。
你必须严格按要求输出 JSON，禁止解释。
```

**User Prompt 模板**：

```
请基于以下商品信息，输出 JSON 描述广告切入角度。

商品信息:
{product_json}

输出 Schema:
{schema_json}

要求:
1. pain_points 必须覆盖用户真实困扰，至少 2 条；
2. core_selling_points 必须从商品 selling_points 中提炼核心，最多 3-5 条；
3. ad_angle 必须有差异化、具体可执行；
4. target_emotion 用 1-2 个英文单词描述情绪方向；
5. 只输出 JSON，无任何解释或 markdown 标记。
请直接输出 JSON:
```

**代码位置**：`app/agents/product_analysis_agent.py`

**演进历史**：

- **v1.0** (2026-07-01)：初始版本
- **v1.1** (2026-07-08)：增加 "target_emotion 限定 1-2 个英文单词" 约束，减少输出长度漂移

**输出 Schema**（`ProductAnalysisSchema`）：

```python
{
    "pain_points": ["string"],          # 2-5 条
    "target_users": ["string"],         # 1-5 条
    "core_selling_points": ["string"],  # 2-5 条
    "ad_angle": "string",               # ≥ 4 字符
    "target_emotion": "string"          # 如 relief, excitement, security
}
```

---

### 2.2 Agent 2：广告脚本 (script_generation, v1.2)

**角色**：5 年经验 TikTok 爆款脚本写手

**System Prompt**：

```
你是 5 年经验的 TikTok 爆款广告脚本写手，写过 100+ 跑量素材。
你的脚本特点是：前 3 秒必抓人，痛点具体可信，CTA 明确。
严格按要求输出 JSON，禁止解释。
```

**User Prompt 模板**：

```
请基于以下商品信息生成一段 {duration} 秒短视频带货脚本。

商品信息:
{product_json}

卖点分析:
{product_analysis_json}

目标平台: {platform}, 总时长: {duration} 秒

输出 Schema:
{schema_json}

要求:
1. hook 必须能在 3 秒内抓住注意力，使用反问 / 痛点提问 / 惊人数据；
2. problem 必须具体，描述用户使用场景和情绪；
3. solution 必须把核心卖点融进具体画面；
4. proof 要给出信任增强（用户数、评价、销量、奖项等）；
5. cta 必须明确指令式（点击 / 立刻 / 立即 / 下单 等动词开头）；
6. full_script 串联 5 段，全长不超过 80 个中文字符每秒；
7. 严格符合 JSON Schema；
8. 只输出 JSON。

[可选] 上次评估反馈（必须修正）:
{failure_feedback}

请直接输出 JSON:
```

**代码位置**：`app/agents/script_agent.py`

**演进历史**：

- **v1.0** (2026-07-01)：初始版本
- **v1.1** (2026-07-05)：增加 "full_script 全长不超过 80 字/秒" 时长约束
- **v1.2** (2026-07-08)：增加 failure_feedback 注入逻辑，支持评估反馈重试

**输出 Schema**（`ScriptSchema`）：

```python
{
    "hook": "string",         # 10-80 字符
    "problem": "string",      # 10-120 字符
    "solution": "string",     # 10-120 字符
    "proof": "string",        # 10-120 字符
    "cta": "string",          # 5-60 字符
    "full_script": "string"   # 80-400 字符
}
```

---

### 2.3 Agent 3：分镜规划 (storyboard_planning, v1.1)

**角色**：广告分镜导演

**System Prompt**：

```
你是广告分镜导演，熟悉短视频拍摄节奏与镜头语言。
严格按 Schema 输出 JSON。
```

**User Prompt 模板**：

```
请把以下脚本拆分为适配 {duration} 秒短视频的分镜表。

脚本:
{script_json}

输出 Schema:
{schema_json}

要求:
1. storyboard 数量 3-8 个；
2. 每个 scene 时长 (duration) 之和 ≤ 总时长 +2 秒；
3. material_type 必须覆盖 pain_point_scene / demo_scene / proof_scene / cta_scene 中的至少 3 种；
4. 镜头语言使用 cinematic 词汇（close-up / wide / pan / cut / medium / over-the-shoulder）；
5. visual 描述具体可拍摄的画面，不要抽象（如 '白领戴上风扇吹起头发' 而非 '展示产品'）；
6. subtitle 不超过 18 个字符；
7. 只输出 JSON。
请直接输出 JSON:
```

**代码位置**：`app/agents/storyboard_agent.py`

**演进历史**：

- **v1.0** (2026-07-01)：初始版本
- **v1.1** (2026-07-08)：增加 "material_type 覆盖至少 3 种" 约束，避免全用同一类镜头

**输出 Schema**（`StoryboardSchema`）：

```python
{
    "storyboard": [
        {
            "scene_id": 1,            # 1-10
            "duration": 3,            # 1-8 秒
            "visual": "string",       # ≥ 10 字符
            "subtitle": "string",     # ≥ 5 字符
            "voiceover": "string",    # ≥ 5 字符
            "camera_shot": "string",  # close-up/wide/medium/pan/cut
            "material_type": "string" # pain_point_scene/demo_scene/proof_scene/cta_scene
        }
    ]  # 3-8 个 scene
}
```

---

### 2.4 Agent 4：素材建议 (material_suggestion, v1.0)

**角色**：短视频素材采购

**System Prompt**：

```
你是短视频素材采购，熟悉国内外素材库（千图、千库、Pexels 等）。
严格按 Schema 输出 JSON。
```

**User Prompt 模板**：

```
请为以下分镜表的每个镜头推荐素材。

分镜表:
{storyboard_json}

输出 Schema:
{schema_json}

要求:
1. materials 数组长度 = storyboard 数组长度；
2. 每个 scene_id 必须与 storyboard 一一对应；
3. material_keyword 必须给出可以直接搜库的英文关键词；
4. material_type 与 storyboard 的 material_type 一致；
5. source 写 'mock_library' 即可，未来可对接真实 API；
6. description 简明描述理想素材的样子；
7. 只输出 JSON。
请直接输出 JSON:
```

**代码位置**：`app/agents/material_agent.py`

**输出 Schema**（`MaterialSuggestionSchema`）：

```python
{
    "materials": [
        {
            "scene_id": 1,
            "material_keyword": "sweating commuter subway",
            "material_type": "pain_point_scene",
            "source": "mock_library",
            "description": "通勤人群地铁车厢出汗特写 8 秒素材"
        }
    ]
}
```

---

### 2.5 Agent 5：质量评估 (quality_evaluation, v1.0)

**角色**：广告审核员

**System Prompt**：

```
你是一名广告审核员，从用户角度评估短视频脚本是否符合投放标准。
你需要严格、结构化地输出评估结果。
```

**User Prompt 模板**：

```
请评估下面这条广告的执行结果，给出 0-100 评分与详细问题列表。

原始商品信息:
{product_json}

脚本输出:
{script_json}

分镜输出:
{storyboard_json}

素材输出:
{material_json}

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

输出 Schema:
{schema_json}

要求:
1. score 必须是 0-100 整数；
2. passed = (score >= 70) AND (risk_level != 'high')；
3. issues 数组列出所有问题，每条 issue 的 type 字段必须是:
   - SELLING_POINT_DRIFT
   - STORYBOARD_MISSING
   - CONTENT_TOO_LONG
   - JSON_PARSE_ERROR
   - SCHEMA_VALIDATION_ERROR
   - PLATFORM_MISMATCH
   - RISKY_CLAIM
   中的一种；
4. suggested_fix 给具体修复指令（如果 passed=true 可留空字符串）；
5. 只输出 JSON。
请直接输出 JSON:
```

**代码位置**：`app/agents/evaluation_agent.py`

**输出 Schema**（`EvaluationSchema`）：

```python
{
    "score": 87,                    # 0-100
    "passed": True,
    "issues": [
        {"type": "SELLING_POINT_DRIFT", "detail": "..."}
    ],
    "risk_level": "low",            # low/medium/high
    "suggested_fix": "..."
}
```

---

### 2.6 Agent 6：失败修复 (repair, v1.0)

**角色**：资深修复工程师

**System Prompt**：

```
你是一名资深的修复工程师，根据下游评估反馈，定向修复上游输出。
只输出修复后的 JSON，禁止解释。
```

**User Prompt 模板**：

```
目标 step: {target_step}

失败反馈:
{failure_feedback}

原始输出:
{original_output_json}

目标 Schema:
{schema_json}

要求:
1. 根据失败反馈做定向修复，不要随便重写；
2. 保持原始输出中可用的部分；
3. 严格符合 Schema；
4. 只输出 JSON。
请直接输出 JSON:
```

**代码位置**：`app/agents/repair_agent.py`

**特点**：

- 这是一个**非业务节点**，专门处理 JUDGE_REJECTED 后的局部修复
- 根据 target_step 动态加载对应 Schema
- 输入是上游 step 的输出 + Judge 反馈，输出是修复后的输出

---

## 3. 自动 Repair Prompt（不是独立 Agent）

除了 6 个业务 Agent 外，系统还有**自动 JSON repair prompt**，由 `services/json_validator.py:build_repair_prompt` 动态生成：

```
你刚才生成的 JSON 不符合目标 Schema，校验失败。
Schema: {schema_name}

目标 Schema (JSON Schema 7.0):
{schema}

你上一次的输出:
{raw_content}

校验错误列表:
- loc=storyboard/0/duration: field required
- loc=hook: string too short

要求:
1. 只返回 JSON 内容，不要任何 markdown、解释或前后缀；
2. 严格遵循上述 Schema 的字段名、类型与约束；
3. 修复所有被指出的错误，不要新增未定义的字段。
请直接输出合法 JSON:
```

这个 prompt 不需要版本化，因为它完全由校验错误自动生成。

---

## 4. A/B 测试方法

### 4.1 流量切分策略

按 task_id hash 切分：

```python
import hashlib

def pick_prompt_version(task_id: str, step_id: str) -> str:
    """50% 走 v1.1 (新版本), 50% 走 v1.0 (旧版本)"""
    h = hashlib.md5(f"{task_id}:{step_id}".encode()).hexdigest()
    bucket = int(h[:8], 16) % 100
    return "v1.1" if bucket < 50 else "v1.0"
```

### 4.2 评估指标

A/B 测试对比两个版本的：

| 指标 | 查询方式 |
|------|---------|
| 成功率 | `tasks WHERE prompt_version='X' AND status='success'` / total |
| 平均耗时 | `AVG(latency_ms)` |
| JSON 失败率 | `COUNT(json_failures) / COUNT(total)` |
| Judge 通过率 | `AVG(passed)` |
| 平均质量分 | `AVG(score)` |

### 4.3 SQL 例子

```sql
-- 对比 v1.0 vs v1.1 的 script_generation 成功率
SELECT
    ts.prompt_version,
    COUNT(*) AS total,
    SUM(CASE WHEN ts.status = 'success' THEN 1 ELSE 0 END) AS success,
    ROUND(AVG(ts.latency_ms), 0) AS avg_latency_ms,
    SUM(CASE WHEN ts.failure_reason = 'JSON_PARSE_ERROR' THEN 1 ELSE 0 END) AS json_failures
FROM task_steps ts
WHERE ts.step_id = 'script_generation'
  AND ts.created_at > now() - interval '7 days'
GROUP BY ts.prompt_version;
```

### 4.4 灰度发布

```
Day 1-3:   10% 流量到 v1.1 (其余 v1.0)
Day 4-6:   30% 流量到 v1.1
Day 7-9:   50% 流量到 v1.1
Day 10+:   100% 流量到 v1.1 (删除 v1.0 fallback)
```

### 4.5 决策依据

| 新版本 vs 旧版本 | 决策 |
|------------------|------|
| 新版成功率 +5% 以上，且耗时未显著增加 | 灰度放量 |
| 新版成功率 +5% 以上，但耗时增加 50% 以上 | 调优后重测 |
| 新版成功率无显著差异 | 保留旧版（避免风险） |
| 新版成功率 -5% | 回滚到旧版 |

---

## 5. Prompt 版本管理工具（未来）

### 5.1 集中存储

当前 Prompt 直接写在 Agent 类里。生产建议集中到 Langfuse Prompt Management：

```python
from langfuse import Langfuse

lf = Langfuse(public_key="...", secret_key="...", host="...")

# 拉取最新 prompt
prompt = lf.get_prompt("script_generation", version=1)
system_prompt = prompt.prompt

# 调用
completion = openai.chat.completions.create(
    model="...",
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ],
)
```

### 5.2 版本对比 UI

Langfuse Web UI 提供 Prompt 版本对比，可以高亮差异。

### 5.3 自动回归

每次 Prompt 变更后自动跑 `evalset`：

```python
# 未来: scripts/regression.py
async def run_regression(prompt_version: str):
    """对固定测试集跑新版本 Prompt，检查质量分不退化"""
    test_cases = load_evalset()  # 50 个固定 product 信息
    results = await asyncio.gather(*[
        run_pipeline(case, prompt_version) for case in test_cases
    ])
    avg_score = sum(r["quality_score"] for r in results) / len(results)
    assert avg_score > BASELINE_SCORE, f"质量分退化: {avg_score} < {BASELINE_SCORE}"
```

---

## 6. Prompt 优化 checklist

每次优化 Prompt 前确认：

- [ ] 当前版本成功率 / JSON 失败率是多少？
- [ ] 优化目标是降低 JSON 失败率？提高 Judge 通过率？减少 Token 消耗？
- [ ] 改了哪一条约束？变更理由是什么？
- [ ] 新版本是否在 evalset 上验证过？
- [ ] 是否需要同步更新 Schema 校验？

---

## 附录：Prompt 文件清单

| Agent | 文件 | 当前版本 |
|-------|------|---------|
| product_analysis | `app/agents/product_analysis_agent.py` | v1.1 |
| script_generation | `app/agents/script_agent.py` | v1.2 |
| storyboard_planning | `app/agents/storyboard_agent.py` | v1.1 |
| material_suggestion | `app/agents/material_agent.py` | v1.0 |
| quality_evaluation | `app/agents/evaluation_agent.py` | v1.0 |
| repair | `app/agents/repair_agent.py` | v1.0 |
| 自动 JSON repair | `app/services/json_validator.py:101-125` | (动态) |