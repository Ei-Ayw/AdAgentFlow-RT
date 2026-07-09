# AdAgentFlow API 文档

> 完整 API 参考。所有 endpoint 都基于 OpenAPI / Swagger 自动生成（`/docs` 和 `/openapi.json`）。

**Base URL**: `http://localhost:8000/api/v1`

**OpenAPI 文档**: http://localhost:8000/docs

---

## 目录

- [Tasks API](#tasks-api)
- [Dead-Letters API](#dead-letters-api)
- [Dashboard API](#dashboard-api)
- [Traces API](#traces-api)
- [System API](#system-api)

---

## Tasks API

### POST `/tasks/submit`

提交广告生成任务，立即返回 `task_id`，后台异步执行。

**Request Body** (application/json):

```json
{
  "product_name": "Portable Neck Fan",
  "target_user": "commuters and outdoor workers",
  "selling_points": ["hands-free cooling", "long battery life", "lightweight design"],
  "platform": "TikTok",
  "style": "dramatic before-after ad",
  "duration": 15
}
```

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `product_name` | string | ✅ | - | 商品名称 |
| `target_user` | string | ❌ | "" | 目标用户描述 |
| `selling_points` | string[] | ❌ | ["hands-free cooling", "long battery life"] | 卖点列表 |
| `platform` | string | ❌ | "TikTok" | 平台 (TikTok / Instagram / YouTube Shorts) |
| `style` | string | ❌ | "dramatic before-after ad" | 风格 |
| `duration` | int | ❌ | 15 | 时长（秒），范围 [5, 60] |

**Response 200**:

```json
{
  "task_id": "task_1720600000_a1b2c3d4",
  "trace_id": "trace_1720600000_e5f6g7h8",
  "status": "queued",
  "message": "任务已提交，请用 task_id 轮询进度"
}
```

**错误码**：

| 状态码 | 含义 |
|--------|------|
| 422 | 请求参数校验失败（缺 product_name、duration 越界等） |
| 500 | 数据库 / 队列异常 |

**示例**：

```bash
curl -X POST http://localhost:8000/api/v1/tasks/submit \
  -H "Content-Type: application/json" \
  -d '{
    "product_name": "Portable Neck Fan",
    "platform": "TikTok",
    "duration": 15,
    "selling_points": ["hands-free cooling", "long battery life"]
  }'
```

```python
import requests

resp = requests.post(
    "http://localhost:8000/api/v1/tasks/submit",
    json={
        "product_name": "Portable Neck Fan",
        "platform": "TikTok",
        "duration": 15,
        "selling_points": ["hands-free cooling"],
    },
)
task_id = resp.json()["task_id"]
```

```javascript
const resp = await fetch("http://localhost:8000/api/v1/tasks/submit", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    product_name: "Portable Neck Fan",
    platform: "TikTok",
    duration: 15,
    selling_points: ["hands-free cooling"],
  }),
});
const data = await resp.json();
console.log(data.task_id);
```

---

### GET `/tasks/{task_id}`

查询任务详情 + 所有 step 状态。

**Response 200**:

```json
{
  "task_id": "task_1720600000_a1b2c3d4",
  "trace_id": "trace_1720600000_e5f6g7h8",
  "status": "success",
  "product_name": "Portable Neck Fan",
  "platform": "TikTok",
  "style": "dramatic before-after ad",
  "duration": 15,
  "retry_count": 0,
  "last_failure_reason": null,
  "created_at": "2026-07-09T10:00:00",
  "updated_at": "2026-07-09T10:00:18",
  "finished_at": "2026-07-09T10:00:18",
  "steps": [
    {
      "step_id": "product_analysis",
      "step_name": "商品理解 Agent",
      "status": "success",
      "retry_count": 0,
      "failure_reason": null,
      "latency_ms": 2300,
      "started_at": "2026-07-09T10:00:00",
      "finished_at": "2026-07-09T10:00:02"
    },
    {
      "step_id": "script_generation",
      "step_name": "广告脚本 Agent",
      "status": "success",
      "retry_count": 0,
      "failure_reason": null,
      "latency_ms": 4100,
      "started_at": "2026-07-09T10:00:02",
      "finished_at": "2026-07-09T10:00:06"
    }
  ],
  "output_payload": {
    "quality_score": 87
  }
}
```

**错误码**：

| 状态码 | 含义 |
|--------|------|
| 404 | 任务不存在 |

---

### GET `/tasks/`

分页列出任务，支持状态过滤。

**Query Parameters**:

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `status` | string | null | 可选：created / queued / running / evaluating / retrying / success / failed / dead_letter / manual_review |
| `limit` | int | 20 | 范围 [1, 200] |
| `offset` | int | 0 | 偏移量 |

**Response 200**:

```json
{
  "total": 1234,
  "limit": 20,
  "offset": 0,
  "items": [
    {
      "task_id": "task_xxx",
      "status": "success",
      "product_name": "...",
      "platform": "TikTok",
      "retry_count": 0,
      "last_failure_reason": null,
      "created_at": "2026-07-09T10:00:00",
      "finished_at": "2026-07-09T10:00:18"
    }
  ]
}
```

---

## Dead-Letters API

### GET `/dead-letters/`

列出死信任务（失败超 max_retry 后进入）。

**Query Parameters**:

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `resolved` | bool | null | 已解决 / 未解决 |
| `limit` | int | 50 | 范围 [1, 200] |
| `offset` | int | 0 | 偏移量 |

**Response 200**:

```json
{
  "total": 8,
  "items": [
    {
      "id": 123,
      "task_id": "task_xxx",
      "step_id": "script_generation",
      "failure_reason": "SCHEMA_VALIDATION_ERROR",
      "retry_count": 3,
      "error_message": "field storyboard[0].duration is missing",
      "resolved": false,
      "created_at": "2026-07-09T10:00:00"
    }
  ]
}
```

### GET `/dead-letters/{dl_id}`

查看死信详情（含 input_payload 和 last_output）。

**Response 200**:

```json
{
  "id": 123,
  "task_id": "task_xxx",
  "step_id": "script_generation",
  "failure_reason": "SCHEMA_VALIDATION_ERROR",
  "input_payload": {...},
  "last_output": {...},
  "retry_count": 3,
  "error_message": "field storyboard[0].duration is missing",
  "resolved": false,
  "created_at": "2026-07-09T10:00:00"
}
```

### POST `/dead-letters/{task_id}/resume`

人工接管死信任务，重新派发到队列头部。

**Response 200**:

```json
{
  "task_id": "task_xxx",
  "status": "queued",
  "message": "已重新派发到队列"
}
```

**错误码**：

| 状态码 | 含义 |
|--------|------|
| 400 | 任务不在 dead_letter 状态 |
| 404 | 任务不存在 |

**示例**：

```bash
curl -X POST http://localhost:8000/api/v1/dead-letters/task_1720600000_xxx/resume
```

### POST `/dead-letters/{dl_id}/resolve`

标记死信为已解决（不重新派发）。

**Response 200**:

```json
{
  "id": 123,
  "resolved": true
}
```

---

## Dashboard API

### GET `/dashboard/overview`

Dashboard 主面板数据，一屏拉齐。

**Response 200**:

```json
{
  "task_summary": {
    "total_tasks": 1234,
    "success": 1172,
    "failed": 12,
    "dead_letter": 8,
    "running": 42,
    "end_to_end_success_rate": 94.97
  },
  "performance": {
    "avg_latency_seconds": 18.3,
    "avg_retry_count": 0.42,
    "total_llm_calls": 6170,
    "json_failure_rate": 4.8,
    "dead_letter_rate": 0.65,
    "avg_quality_score": 82.5,
    "judge_pass_rate": 91.2
  },
  "node_success_rates": [
    {
      "step_id": "product_analysis",
      "total_executions": 1234,
      "success_executions": 1220,
      "success_rate": 98.87
    },
    {
      "step_id": "script_generation",
      "total_executions": 1234,
      "success_executions": 1180,
      "success_rate": 95.62
    }
  ],
  "failure_top_5": [
    {"reason": "SCHEMA_VALIDATION_ERROR", "count": 45},
    {"reason": "JSON_PARSE_ERROR", "count": 28},
    {"reason": "MODEL_TIMEOUT", "count": 15}
  ],
  "unresolved_dead_letters": [
    {
      "id": 123,
      "task_id": "task_xxx",
      "step_id": "script_generation",
      "failure_reason": "SCHEMA_VALIDATION_ERROR",
      "created_at": "2026-07-09T10:00:00"
    }
  ]
}
```

### GET `/dashboard/tasks-summary`

按状态聚合任务分布。

**Response 200**:

```json
{
  "created": 5,
  "queued": 12,
  "running": 25,
  "evaluating": 3,
  "retrying": 2,
  "success": 1172,
  "failed": 12,
  "dead_letter": 8,
  "manual_review": 3
}
```

### GET `/dashboard/latency-trend`

按小时聚合耗时趋势。

**Query Parameters**:

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `hours` | int | 24 | 时间范围（小时） |

**Response 200**:

```json
[
  {
    "bucket": "2026-07-09 10:00:00",
    "count": 45,
    "avg_latency_seconds": 18.3
  },
  {
    "bucket": "2026-07-09 11:00:00",
    "count": 52,
    "avg_latency_seconds": 17.8
  }
]
```

### GET `/dashboard/agent-metrics`

节点级聚合指标（含 latency、token、json failure）。

**Response 200**:

```json
[
  {
    "step_name": "product_analysis",
    "total_executions": 1234,
    "success_executions": 1220,
    "failed_executions": 14,
    "retry_executions": 5,
    "avg_latency_ms": 2350,
    "json_failures": 8,
    "schema_failures": 6,
    "success_rate": 98.87,
    "last_updated_at": "2026-07-09T11:00:00"
  }
]
```

### GET `/dashboard/health-check`

系统全组件健康自检。

**Response 200**:

```json
{
  "postgres": "ok",
  "redis": "ok",
  "rabbitmq": "ok"
}
```

---

## Traces API

### GET `/traces/{trace_id}`

按 trace_id 查询全链路事件。

**Response 200**:

```json
{
  "trace_id": "trace_1720600000_e5f6g7h8",
  "events": [
    {
      "id": 1,
      "task_id": "task_xxx",
      "step_id": "product_analysis",
      "event_type": "step.start",
      "event_status": "running",
      "latency_ms": 0,
      "model_name": null,
      "prompt_version": null,
      "token_cost": 0,
      "error_message": null,
      "created_at": "2026-07-09T10:00:00"
    },
    {
      "id": 2,
      "task_id": "task_xxx",
      "step_id": "product_analysis",
      "event_type": "step.success",
      "event_status": "success",
      "latency_ms": 2300,
      "model_name": "MiniMax-M3",
      "prompt_version": "v1.1",
      "token_cost": 450,
      "error_message": null,
      "created_at": "2026-07-09T10:00:02"
    }
  ]
}
```

**错误码**：

| 状态码 | 含义 |
|--------|------|
| 404 | trace 不存在 |

### GET `/traces/by-task/{task_id}`

按 task_id 查询该任务的所有 trace 事件（一个任务可能有多个 trace_id 用于 retry）。

---

## System API

### GET `/`

返回 Dashboard 首页（HTML）。

### GET `/health`

简单健康检查。

**Response 200**:

```json
{
  "status": "healthy",
  "service": "AdAgentFlow",
  "version": "1.0.0"
}
```

**Response 503**（异常）:

```json
{
  "status": "unhealthy",
  "error": "could not connect to server: Connection refused"
}
```

### GET `/docs`

Swagger UI（自动生成）。

### GET `/openapi.json`

OpenAPI 3.0 schema（自动生成）。

---

## 完整调用流程示例

```python
"""完整提交 → 轮询 → 查 trace 流程"""
import time
import requests

BASE = "http://localhost:8000/api/v1"

# 1. 提交
resp = requests.post(f"{BASE}/tasks/submit", json={
    "product_name": "Portable Neck Fan",
    "platform": "TikTok",
    "duration": 15,
    "selling_points": ["hands-free cooling", "long battery life"],
})
data = resp.json()
task_id = data["task_id"]
trace_id = data["trace_id"]
print(f"提交成功: task_id={task_id}")

# 2. 轮询
for i in range(60):
    detail = requests.get(f"{BASE}/tasks/{task_id}").json()
    status = detail["status"]
    print(f"[{i}] status={status}")
    if status in ("success", "failed", "dead_letter", "manual_review"):
        break
    time.sleep(2)

# 3. 查 trace
events = requests.get(f"{BASE}/traces/{trace_id}").json()["events"]
print(f"trace events: {len(events)}")

# 4. 查 Dashboard
overview = requests.get(f"{BASE}/dashboard/overview").json()
print(f"端到端成功率: {overview['task_summary']['end_to_end_success_rate']}%")
```

---

## 错误码总览

| 状态码 | 含义 | 常见原因 |
|--------|------|---------|
| 200 | 成功 | - |
| 400 | 请求参数错误 | 任务不在 dead_letter 状态 |
| 404 | 资源不存在 | task_id / trace_id / dl_id 不存在 |
| 422 | 参数校验失败 | 缺 product_name、duration 越界等 |
| 500 | 服务器内部错误 | DB / Redis / RabbitMQ 异常 |

---

## 限流策略（未来）

当前未实现限流，生产建议加：

- API 层：slowapi 限流（默认 100 req/min per IP）
- Worker 层：RabbitMQ prefetch + Worker concurrency 控制
- LLM 层：按 model + tenant 限速（令牌桶）