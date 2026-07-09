AdAgentFlow 完整蓝图
一、项目定位
项目名：AdAgentFlow：面向电商短视频广告生成的多 Agent 长任务可靠性框架
一句话介绍：
AdAgentFlow 是一个面向电商短视频广告生成场景的多 Agent 长任务执行框架，重点解决多 Agent 协作中的结构化输出失败、卖点偏移、长任务中断、重复消费、失败恢复与链路不可观测问题。
它不是普通的“广告文案生成器”，而是一个Agent 系统工程项目。
它要证明的能力是：
多 Agent 工作流怎么编排；
长任务怎么异步执行；
节点失败怎么重试；
Worker 挂了怎么恢复；
LLM 输出 JSON 错了怎么修复；
多次失败怎么进死信；
重复消费怎么靠幂等控制；
每个任务怎么 trace；
最后怎么统计成功率、失败率、重试率和耗时。
这个方向和他现在简历里的多 Agent 视频生产、评估纠偏、任务状态机、死信队列、Redis 幂等键等经历是呼应的，但场景换成电商广告，不会显得直接复刻公司项目。

需要使用数据库等服务直接拉取docker，大模型的可以用minmax（本地拉起llm服务也可以，视频生成可以mock）：env": {
    "ANTHROPIC_AUTH_TOKEN": "sk-cp-5jz0cG8fkE-yRSQcZCTvxtXEHmnwYexM1s9vvRWAsJOaP9LbxuJP0txihlkLmows_Chij9_MI7g2aXC5B7xB_IlpaFOY8jTiX9UpwaHxkyIoo-tJN8crSg8",
    "ANTHROPIC_BASE_URL": "https://api.minimaxi.com/anthropic",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "MiniMax-M3",

二、最终简历目标话术
先把最终简历怎么写定下来，然后所有实现都围绕这些话术做。
简历项目写法
AdAgentFlow：面向电商短视频广告生成的多 Agent 长任务可靠性框架｜核心开发
技术栈：FastAPI / RabbitMQ / Redis / PostgreSQL / Docker / Langfuse / JSON Schema / LLM-as-Judge
• 面向电商短视频广告生成场景，设计并实现多 Agent 长任务执行框架，将商品卖点分析、广告脚本生成、分镜规划、素材建议、质量评估与失败修复拆分为可追踪工作流节点，重点探索多 Agent 协作与高请求量长任务场景下的稳定执行机制。
• 基于 FastAPI + RabbitMQ 构建异步任务调度链路，用户提交商品信息后返回 task_id，后台由 Worker 池异步执行各 Agent 节点；设计任务状态机维护 queued / running / evaluating / retrying / success / failed / dead_letter 等状态，支持长任务进度查询、失败恢复与执行复盘。
• 针对 LLM 结构化输出不稳定、广告卖点偏移、分镜缺失等问题，引入 JSON Schema 校验、字段完整性检查与 LLM-as-Judge 评估机制；评估不通过时触发失败反馈重试、局部重生成或人工审核，提升多步骤 Agent 链路的可控性与一致性。
• 设计失败重试、死信队列与幂等控制机制，基于 task_id + step_id 标识节点执行，结合 Redis 幂等键与数据库状态持久化，避免 Worker 重复消费导致的重复生成、状态覆盖与结果污染；对超过最大重试次数的任务记录失败原因并进入 dead-letter 流程。
• 构建任务级可观测与评测指标体系，基于 trace_id 记录节点耗时、模型调用次数、Token 消耗、重试次数、JSON 解析失败、评估结果与失败原因分布，并在 Dashboard 中展示端到端成功率、节点成功率、平均耗时、平均重试次数与失败 Top 原因，用于定位 Agent 长链路稳定性瓶颈。
• 通过并发任务压测与故障模拟，验证模型超时、JSON 输出异常、Worker 异常退出、队列堆积和重复消费等场景下的任务恢复、幂等控制、失败重试与死信处理机制，形成压测报告与高请求量扩展方案。
下面所有蓝图，都对应这 6 条简历 bullet。
￼
三、项目整体架构
1. 系统分层
整体分成 7 层：
复制
用户请求层
  ↓
API 接入层 FastAPI
  ↓
任务调度层 RabbitMQ / Redis Queue
  ↓
Worker 执行层
  ↓
Agent 工作流层
  ↓
评估纠偏层 JSON Schema + LLM-as-Judge
  ↓
状态与观测层 PostgreSQL + Redis + Langfuse / Dashboard
￼
2. 核心链路
复制
用户提交商品信息
  ↓
FastAPI 创建 task_id
  ↓
任务写入 PostgreSQL
  ↓
任务进入 RabbitMQ 队列
  ↓
Worker 消费任务
  ↓
执行商品理解 Agent
  ↓
执行广告脚本 Agent
  ↓
执行分镜规划 Agent
  ↓
执行素材建议 Agent
  ↓
执行质量评估 Agent
  ↓
如果通过：生成最终结果
  ↓
如果失败：进入修复 Agent / 重试 / 死信队列
  ↓
Dashboard 展示状态、耗时、失败原因、重试次数、成功率
￼
四、业务场景设计
输入
用户输入一个商品广告需求：
JSON
复制
￼
{
  "product_name": "Portable Neck Fan",
  "target_user": "commuters and outdoor workers",
  "selling_points": [
    "hands-free cooling",
    "long battery life",
    "lightweight design"
  ],
  "platform": "TikTok",
  "style": "dramatic before-after ad",
  "duration": 15
}
￼
输出
最终生成：
JSON
复制
￼
{
  "task_id": "task_20260708_001",
  "status": "success",
  "ad_title": "Beat the Heat Anywhere",
  "script": "...",
  "storyboard": [
    {
      "scene_id": 1,
      "duration": 3,
      "visual": "...",
      "subtitle": "...",
      "voiceover": "..."
    }
  ],
  "material_suggestions": [...],
  "quality_report": {
    "score": 87,
    "selling_point_consistency": "pass",
    "platform_fit": "pass",
    "risk_level": "low"
  }
}
￼
五、多 Agent 工作流设计
Agent 1：商品理解 Agent
负责从商品信息中提取：
痛点；
目标用户；
核心卖点；
广告角度；
情绪方向。
输出 Schema：
JSON
复制
￼
{
  "pain_points": ["string"],
  "target_users": ["string"],
  "core_selling_points": ["string"],
  "ad_angle": "string",
  "target_emotion": "string"
}
￼
Agent 2：广告脚本 Agent
负责生成 15 秒短视频脚本。
要求包含：
前 3 秒钩子；
痛点展示；
产品解决方案；
信任增强；
行动号召。
输出 Schema：
JSON
复制
￼
{
  "hook": "string",
  "problem": "string",
  "solution": "string",
  "proof": "string",
  "cta": "string",
  "full_script": "string"
}
￼
Agent 3：分镜规划 Agent
负责把脚本拆成镜头。
输出 Schema：
JSON
复制
￼
{
  "storyboard": [
    {
      "scene_id": 1,
      "duration": 3,
      "visual": "string",
      "subtitle": "string",
      "voiceover": "string",
      "camera_shot": "string",
      "material_type": "string"
    }
  ]
}
￼
Agent 4：素材建议 Agent
负责给每个镜头匹配素材建议。
可以先用 mock 素材库，不需要真接视频生成。
输出 Schema：
JSON
复制
￼
{
  "materials": [
    {
      "scene_id": 1,
      "material_keyword": "sweating commuter",
      "material_type": "pain_point_scene",
      "source": "mock_library"
    }
  ]
}
￼
Agent 5：质量评估 Agent
这是项目亮点之一。
评估维度：
卖点是否一致；
分镜是否完整；
是否符合平台风格；
是否存在夸大表达；
脚本长度是否适合 15 秒；
JSON 结构是否完整；
是否缺失 CTA。
输出 Schema：
JSON
复制
￼
{
  "score": 85,
  "passed": true,
  "issues": [],
  "risk_level": "low",
  "suggested_fix": ""
}
￼
Agent 6：失败修复 Agent
根据失败原因局部修复。
例如：
JSON 错误 → 修 JSON；
卖点偏移 → 重写脚本；
分镜缺失 → 重写分镜；
脚本过长 → 压缩脚本；
评估不通过 → 根据评估反馈重试。
￼
六、任务状态机设计
任务级状态
复制
created
queued
running
evaluating
retrying
success
failed
dead_letter
manual_review
节点级状态
复制
pending
running
success
failed
retrying
skipped
状态流转
正常链路：
复制
created → queued → running → evaluating → success
重试链路：
复制
created → queued → running → evaluating → retrying → running → evaluating → success
失败链路：
复制
created → queued → running → failed → retrying → running → failed → dead_letter
人工审核链路：
复制
created → queued → running → evaluating → manual_review
￼
七、数据库设计
1. tasks 表
记录任务主信息。
SQL
复制
￼
CREATE TABLE tasks (
  id BIGSERIAL PRIMARY KEY,
  task_id VARCHAR(64) UNIQUE NOT NULL,
  status VARCHAR(32) NOT NULL,
  product_name VARCHAR(255),
  platform VARCHAR(64),
  style VARCHAR(128),
  duration INT,
  retry_count INT DEFAULT 0,
  max_retry INT DEFAULT 3,
  trace_id VARCHAR(64),
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);
￼
2. task_steps 表
记录每个 Agent 节点状态。
SQL
复制
￼
CREATE TABLE task_steps (
  id BIGSERIAL PRIMARY KEY,
  task_id VARCHAR(64) NOT NULL,
  step_id VARCHAR(64) NOT NULL,
  step_name VARCHAR(128),
  status VARCHAR(32),
  input_payload JSONB,
  output_payload JSONB,
  retry_count INT DEFAULT 0,
  failure_reason VARCHAR(128),
  started_at TIMESTAMP,
  finished_at TIMESTAMP,
  UNIQUE(task_id, step_id)
);
￼
3. task_traces 表
记录链路追踪。
SQL
复制
￼
CREATE TABLE task_traces (
  id BIGSERIAL PRIMARY KEY,
  trace_id VARCHAR(64),
  task_id VARCHAR(64),
  step_id VARCHAR(64),
  event_type VARCHAR(64),
  latency_ms INT,
  model_name VARCHAR(128),
  prompt_version VARCHAR(64),
  token_cost INT,
  error_message TEXT,
  created_at TIMESTAMP
);
￼
4. dead_letters 表
记录死信任务。
SQL
复制
￼
CREATE TABLE dead_letters (
  id BIGSERIAL PRIMARY KEY,
  task_id VARCHAR(64),
  step_id VARCHAR(64),
  failure_reason VARCHAR(128),
  input_payload JSONB,
  last_output JSONB,
  retry_count INT,
  created_at TIMESTAMP
);
￼
5. evaluation_results 表
记录 LLM-as-Judge 结果。
SQL
复制
￼
CREATE TABLE evaluation_results (
  id BIGSERIAL PRIMARY KEY,
  task_id VARCHAR(64),
  step_id VARCHAR(64),
  score INT,
  passed BOOLEAN,
  issues JSONB,
  risk_level VARCHAR(32),
  suggested_fix TEXT,
  created_at TIMESTAMP
);
￼
八、队列设计
RabbitMQ Topic
复制
ad_task.created
ad_task.product_analysis
ad_task.script_generation
ad_task.storyboard_planning
ad_task.material_suggestion
ad_task.quality_evaluation
ad_task.repair
ad_task.dead_letter
Worker 类型
轻量 Worker
处理：
商品分析；
脚本生成；
分镜生成；
JSON 校验；
质量评估。
重型 Worker
处理：
模拟视频生成；
批量任务；
耗时任务；
后续可扩展图像/视频生成。
￼
九、失败类型设计
失败类型要结构化，否则不好统计指标。
复制
JSON_PARSE_ERROR
SCHEMA_VALIDATION_ERROR
SELLING_POINT_DRIFT
STORYBOARD_MISSING
CONTENT_TOO_LONG
MODEL_TIMEOUT
JUDGE_REJECTED
WORKER_CRASH
DUPLICATE_MESSAGE
UNKNOWN_ERROR
失败处理策略
失败类型
处理方式
JSON_PARSE_ERROR
JSON repair prompt
SCHEMA_VALIDATION_ERROR
带 schema 错误反馈重试
SELLING_POINT_DRIFT
重新生成脚本
STORYBOARD_MISSING
重试分镜节点
CONTENT_TOO_LONG
压缩脚本
MODEL_TIMEOUT
指数退避重试 / 切换模型
JUDGE_REJECTED
局部重生成 / 人工审核
WORKER_CRASH
根据状态机恢复
DUPLICATE_MESSAGE
幂等拦截
UNKNOWN_ERROR
记录日志后进入 dead_letter
复制表格
￼
十、重试机制设计
重试策略
最大重试次数：3 次。
重试间隔：
复制
第 1 次：立即重试
第 2 次：延迟 5 秒
第 3 次：延迟 15 秒
超过 3 次：进入 dead_letter
重试时要带失败信息
比如：
JSON
复制
￼
{
  "failure_reason": "SCHEMA_VALIDATION_ERROR",
  "schema_error": "field storyboard[0].duration is missing",
  "previous_output": "{...}"
}
这样修复 Agent 不是盲目重跑，而是根据失败原因修复。
￼
十一、幂等控制设计
这个必须做，因为它能直接支撑简历里的“避免重复消费导致重复生成、状态覆盖与结果污染”。
幂等键设计
复制
idempotent:{task_id}:{step_id}
例如：
复制
idempotent:task_001:script_generation
处理逻辑
Worker 消费消息前：
1. 检查 Redis 是否存在幂等键；
2. 如果存在，说明该节点已经执行或正在执行，直接跳过；
3. 如果不存在，设置幂等键；
4. 执行 Agent 节点；
5. 成功后写入 task_steps；
6. 失败时根据状态决定是否释放幂等键或进入重试。
数据库也要兜底
task_steps 表用：
SQL
复制
￼
UNIQUE(task_id, step_id)
防止重复写入。
￼
十二、LLM-as-Judge 设计
不要让 Judge 只给一个“好/不好”。
要结构化输出：
JSON
复制
￼
{
  "score": 78,
  "passed": false,
  "issues": [
    {
      "type": "SELLING_POINT_DRIFT",
      "detail": "The script focuses too much on fashion instead of cooling."
    }
  ],
  "suggested_fix": "Regenerate the hook and solution part around cooling and outdoor use."
}
Judge 评估维度
维度
说明
selling_point_consistency
是否围绕商品卖点
platform_fit
是否适合 TikTok
storyboard_completeness
分镜是否完整
duration_fit
是否符合 15 秒
risk_control
是否夸大宣传
output_format
JSON 是否合格
复制表格
￼
十三、可观测性设计
每个任务必须有 trace_id
复制
trace_id = trace_20260708_001
每个节点记录
JSON
复制
￼
{
  "trace_id": "trace_001",
  "task_id": "task_001",
  "step_id": "storyboard_planning",
  "status": "retrying",
  "latency_ms": 5300,
  "retry_count": 1,
  "failure_reason": "SCHEMA_VALIDATION_ERROR",
  "model": "gpt-4o-mini",
  "prompt_version": "v1.2",
  "token_cost": 1340
}
Dashboard 展示
第一版 Dashboard 只需要这些：
任务总数；
成功任务数；
失败任务数；
死信任务数；
端到端成功率；
节点成功率；
平均任务耗时；
平均重试次数；
JSON 失败率；
失败原因 Top 5；
单个任务 Trace 详情。
￼
十四、指标体系
项目必须能跑出这些指标。
指标
计算方式
简历用途
端到端成功率
成功任务数 / 总任务数
证明链路能跑通
节点成功率
节点成功次数 / 节点执行次数
定位不稳定节点
JSON 解析失败率
JSON 失败次数 / LLM 调用次数
证明结构化输出治理
平均重试次数
总重试次数 / 总任务数
证明失败恢复能力
平均任务耗时
总耗时 / 总任务数
证明性能意识
Token 消耗
每任务 Token 平均值
证明成本意识
死信率
死信任务数 / 总任务数
证明异常任务治理
Worker 恢复成功率
故障后恢复任务数 / 故障任务数
证明可靠性
重复消费拦截数
被幂等拦截的重复消息数
证明幂等机制有效
失败 Top 原因
按 failure_reason 聚合
证明可复盘能力
复制表格
￼
十五、压测与故障模拟
这个部分是为了支撑简历最后一句：
通过并发任务压测与故障模拟，验证模型超时、JSON 输出异常、Worker 异常退出、队列堆积和重复消费等场景下的任务恢复、幂等控制、失败重试与死信处理机制，形成压测报告与高请求量扩展方案。
压测场景
场景 1：并发提交任务
模拟：
复制
50 个并发任务
100 个并发任务
200 个并发任务
观察：
队列堆积；
平均耗时；
成功率；
失败率；
Worker 消费速度。
￼
场景 2：JSON 输出异常
主动让 LLM 或 mock 模型返回错误 JSON。
验证：
JSON Schema 是否能检测；
repair 是否能修复；
重试次数是否记录；
最终是否成功。
￼
场景 3：Worker 异常退出
在执行中 kill Worker。
验证：
任务状态是否停留在 running；
系统是否能重新捞起任务；
会不会重复写结果；
幂等是否生效。
￼
场景 4：重复消息投递
手动投递两条相同消息。
验证：
是否被 Redis 幂等键拦截；
数据库是否出现重复结果；
状态是否乱序。
￼
场景 5：模型超时
mock 模型 API 超时。
验证：
是否触发 timeout；
是否指数退避重试；
超过次数是否进入 dead_letter。

面向电商短视频广告生成场景,设计多Agent长任务执行框架,将商品理解、脚本生成、分镜规划、素
材建议、质量评估与失败修复拆分为可追踪节点,探索多Agent协作与高请求量长任务下的稳定执行机
制。
基于RabbitMQ构建事件驱动的Agent通信与异步调度链路,通过 taask_id / step_id / trace_id
artifact_ref完成Agent交接,结合任务状态机维护queued/running/evaluating/retrying
success/failed/dead_letter等状态,支持长任务进度追踪与失败恢复。
引入JSON Schema、交接验证与LLM-as-Judge评估机制,对结构化输出错误、卖点偏移、分镜缺失
和Agent交接失败进行检测;评估不通过时触发失败反馈重试、局部重生成、上下文重置或人工审核。
设计沙盒化AgentRunner、失败重试、死信队列与幂等控制机别,通过timeout、最大重试次数、最
大工具调用次数、Redis幕等键和状态机合法转移校验,避免Agent卡死、死循环、无限重试、重复消
费和状态覆盖。
构建evalset驱动的发布闸门与可观测系统,基于Logs/Traces/ Metrics记录节点耗时、Prompt/模
型版本、Token成本、重试次数、失败原因与Judge结果,并通过Dasshboard展示端到端成功率、节
点成功率、死信率、平均耗时和失败Top原因,支持A/B测试、灰度发布与故障复盘
