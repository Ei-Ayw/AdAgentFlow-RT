# AdAgentFlow × Langfuse 可观测集成

> 本文档描述如何把 AdAgentFlow 的 trace / metric 上报 Langfuse，实现 Trace UI、Prompt 版本管理、Token 成本可视化。

---

## 1. Langfuse 简介

[Langfuse](https://langfuse.com/) 是一个开源的 LLM 可观测平台，提供：

- **Trace UI**：可视化每个 LLM 调用的输入输出、耗时、Token
- **Prompt Management**：集中存储 + 版本管理 Prompt
- **Eval**：内置评估指标，支持 LLM-as-Judge 与人工标注
- **Cost Tracking**：按模型统计 Token 成本

---

## 2. 接入步骤

### 2.1 启动 Langfuse（docker compose 已包含）

`docker-compose.yml` 已经定义了 Langfuse 服务：

```yaml
langfuse:
  image: langfuse/langfuse:latest
  container_name: adagentflow-langfuse
  environment:
    DATABASE_URL: postgresql://adagent:adagent_secret_2026@postgres:5432/adagentflow?schema=langfuse
    NEXTAUTH_URL: http://localhost:3000
    NEXTAUTH_SECRET: langfuse_super_secret_change_in_prod
    SALT: langfuse_salt_change_in_prod
  ports:
    - "3000:3000"
```

启动：

```bash
docker compose up -d langfuse
```

访问 http://localhost:3000 ，用任意邮箱注册账号（默认第一个用户是 admin）。

### 2.2 创建 Project & 获取 Key

1. 登录 Langfuse Web UI
2. 进入 **Settings → Projects → New Project**
3. 命名项目：`adagentflow`
4. 进入 **Settings → API Keys → Create API Key**
5. 复制 `Public Key` (pk-lf-...) 和 `Secret Key` (sk-lf-...)

### 2.3 配置环境变量

修改 `.env`：

```bash
LANGFUSE_ENABLED=true
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_PUBLIC_KEY=pk-lf-xxx
LANGFUSE_SECRET_KEY=sk-lf-xxx
```

### 2.4 安装依赖

`requirements.txt` 还没包含 langfuse，需要手动安装：

```bash
pip install langfuse==2.0.0
# 或添加到 requirements.txt 后 docker compose build
```

### 2.5 代码集成

在 `app/services/tracing.py` 中添加 Langfuse 客户端：

```python
"""Trace 服务 - Langfuse + DB 双写
支持 trace_id 全链路追踪
"""
import time
import uuid
from typing import Optional, Dict, Any
from contextlib import contextmanager

from app.core.logging import get_logger
from app.core.config import settings
from app.db.database import session_scope
from app.models.trace import TaskTrace

logger = get_logger()

# ============================================================
# Langfuse 客户端（懒加载）
# ============================================================
_langfuse_client = None


def get_langfuse():
    global _langfuse_client
    if not settings.langfuse_enabled:
        return None
    if _langfuse_client is None:
        from langfuse import Langfuse
        _langfuse_client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    return _langfuse_client


# ============================================================
# trace_id 生成
# ============================================================
def generate_trace_id() -> str:
    return f"trace_{int(time.time())}_{uuid.uuid4().hex[:8]}"


def generate_task_id() -> str:
    return f"task_{int(time.time())}_{uuid.uuid4().hex[:8]}"


# ============================================================
# Tracer - 写 DB + Langfuse
# ============================================================
class Tracer:
    """轻量 tracer - 把事件写到 task_traces 表，同时上报 Langfuse"""

    def __init__(self, trace_id: str):
        self.trace_id = trace_id
        self._langfuse_trace = None
        self._langfuse_generations: Dict[str, Any] = {}

        # Langfuse: 创建顶层 trace
        lf = get_langfuse()
        if lf is not None:
            try:
                self._langfuse_trace = lf.trace(
                    id=trace_id,
                    name="adagentflow_task",
                )
            except Exception as e:
                logger.warning(f"Langfuse trace 创建失败: {e}")

    def record(
        self,
        *,
        task_id: Optional[str] = None,
        step_id: Optional[str] = None,
        event_type: str = "step.event",
        event_status: str = "info",
        latency_ms: int = 0,
        model_name: Optional[str] = None,
        prompt_version: Optional[str] = None,
        token_cost: int = 0,
        error_message: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ):
        """写一条 trace - DB + Langfuse 双写"""
        # 1. 写 DB
        try:
            with session_scope() as db:
                rec = TaskTrace(
                    trace_id=self.trace_id,
                    task_id=task_id,
                    step_id=step_id,
                    event_type=event_type,
                    event_status=event_status,
                    latency_ms=latency_ms,
                    model_name=model_name,
                    prompt_version=prompt_version,
                    token_cost=token_cost,
                    error_message=error_message,
                    extra_metadata=extra_metadata,
                )
                db.add(rec)
        except Exception as e:
            logger.warning(f"写 trace DB 失败 (非致命): {e}")

        # 2. 写 Langfuse
        lf = get_langfuse()
        if lf is not None and self._langfuse_trace is not None:
            try:
                self._write_langfuse_event(
                    task_id=task_id,
                    step_id=step_id,
                    event_type=event_type,
                    event_status=event_status,
                    latency_ms=latency_ms,
                    model_name=model_name,
                    prompt_version=prompt_version,
                    token_cost=token_cost,
                    error_message=error_message,
                    extra_metadata=extra_metadata,
                )
            except Exception as e:
                logger.warning(f"写 Langfuse trace 失败: {e}")

    def _write_langfuse_event(
        self,
        *,
        task_id: str,
        step_id: str,
        event_type: str,
        event_status: str,
        latency_ms: int,
        model_name: str,
        prompt_version: str,
        token_cost: int,
        error_message: str,
        extra_metadata: dict,
    ):
        """Langfuse 事件写入 - step.start / step.success / step.fail"""
        lf = get_langfuse()
        key = f"{task_id}:{step_id}"

        if event_type == "step.start":
            # 创建 generation 节点
            self._langfuse_generations[key] = self._langfuse_trace.generation(
                name=step_id or "step",
                model=model_name or "unknown",
                metadata={
                    "task_id": task_id,
                    "prompt_version": prompt_version,
                    **(extra_metadata or {}),
                },
            )
        elif event_type in ("step.success", "step.fail"):
            gen = self._langfuse_generations.get(key)
            if gen is not None:
                gen.end(
                    output={"status": event_status, "latency_ms": latency_ms},
                    usage={
                        "input": token_cost // 2,   # 近似拆分
                        "output": token_cost // 2,
                        "total": token_cost,
                    },
                    level="ERROR" if event_status == "failed" else "DEFAULT",
                    status_message=error_message,
                )
                del self._langfuse_generations[key]
        else:
            # 通用 span
            self._langfuse_trace.span(
                name=event_type,
                metadata={
                    "task_id": task_id,
                    "step_id": step_id,
                    "event_status": event_status,
                    "latency_ms": latency_ms,
                    **(extra_metadata or {}),
                },
            )


# ============================================================
# 上下文管理器
# ============================================================
@contextmanager
def trace_step(tracer: Tracer, step_id: str, task_id: str = ""):
    """with 上下文 - 自动写开始/结束 trace"""
    start = time.time()
    tracer.record(
        task_id=task_id,
        step_id=step_id,
        event_type="step.start",
        event_status="started",
        latency_ms=0,
    )
    try:
        yield
        latency = int((time.time() - start) * 1000)
        tracer.record(
            task_id=task_id,
            step_id=step_id,
            event_type="step.end",
            event_status="success",
            latency_ms=latency,
        )
    except Exception as e:
        latency = int((time.time() - start) * 1000)
        tracer.record(
            task_id=task_id,
            step_id=step_id,
            event_type="step.end",
            event_status="failed",
            latency_ms=latency,
            error_message=str(e),
        )
        raise


# ============================================================
# 关闭钩子
# ============================================================
def flush_langfuse():
    """进程退出前调用 flush，保证事件不丢"""
    lf = get_langfuse()
    if lf is not None:
        try:
            lf.flush()
        except Exception as e:
            logger.warning(f"Langfuse flush 失败: {e}")
```

### 2.6 在 Agent 中使用（可选增强）

`app/agents/base.py` 的 `AgentResult` 中加入 Langfuse score 上报：

```python
async def run(self, ctx: Dict[str, Any]) -> AgentResult:
    """执行 Agent - 带 Langfuse 上报"""
    from app.services.tracing import get_langfuse

    start = time.time()
    result = AgentResult(success=False, model=self.llm.model, prompt_version=self.prompt_version)

    # Langfuse span 包裹
    lf = get_langfuse()
    span = None
    if lf is not None:
        try:
            span = lf.span(
                name=f"agent.{self.step_id}",
                metadata={"prompt_version": self.prompt_version},
            )
        except Exception:
            pass

    try:
        parsed, llm_resp = await self.llm.generate_json(...)
        # ... 校验 ...
        if span is not None:
            span.end(output={"success": True})
        return result
    except Exception as e:
        if span is not None:
            span.end(output={"success": False}, level="ERROR", status_message=str(e))
        raise
```

### 2.7 重启服务

```bash
docker compose restart api worker-light worker-heavy
```

---

## 3. Trace 关联原理

### 3.1 三种 ID 的关系

```
trace_id (Langfuse + DB)
   │
   ├── task_id (主键)
   │     │
   │     ├── step_id=product_analysis   → step.start / step.success / step.fail
   │     ├── step_id=script_generation  → step.start / step.success / step.fail
   │     ├── step_id=storyboard_planning
   │     ├── step_id=material_suggestion
   │     └── step_id=quality_evaluation
   │
   └── task_id2 (retry 时可能生成新 task_id，但仍属同一 trace_id)
```

- **trace_id**：贯穿整个任务生命周期（即便重试也不变）
- **task_id**：每个任务一个，重试时 task_id 不变
- **step_id**：固定 6 个之一

### 3.2 查询 trace

通过 API：

```bash
# 按 trace_id 查 DB
curl http://localhost:8000/api/v1/traces/{trace_id}

# 按 task_id 查 DB
curl http://localhost:8000/api/v1/traces/by-task/{task_id}
```

通过 Langfuse Web UI：

1. 进入 https://localhost:3000
2. 左侧导航 → **Traces**
3. 搜索 `trace_xxx` 或按 task_id 过滤

---

## 4. Langfuse UI 使用

### 4.1 Trace 详情页

打开一条 trace，可以看到：

```
trace_1720600000_e5f6g7h8
  └─ agent.product_analysis (2300ms, MiniMax-M3, v1.1)
       └─ step.start (latency=0)
       └─ step.success (latency=2300, tokens=450)
  └─ agent.script_generation (4100ms, MiniMax-M3, v1.2)
       └─ step.start
       └─ step.success
  └─ agent.storyboard_planning (3800ms, MiniMax-M3, v1.1)
       └─ step.start
       └─ step.fail (failure_reason=SCHEMA_VALIDATION_ERROR)
       └─ step.start (retry attempt=2)
       └─ step.success
  └─ ...
```

### 4.2 Metrics 面板

进入 **Metrics**：

- **Latency p50 / p95 / p99**：按 step 统计
- **Token Usage**：按 model 统计
- **Cost**：按 model 统计（需要 Langfuse 配置模型价格）
- **Error Rate**：按 step 统计

### 4.3 Prompt Management

1. 进入 **Prompts**
2. 点击 **New Prompt**
3. 命名 `script_generation`，写入内容
4. 在 Agent 中调用：

```python
from langfuse import Langfuse

lf = Langfuse(...)
prompt = lf.get_prompt("script_generation", version=1)
system_prompt = prompt.prompt
```

Langfuse 会自动记录使用了哪个版本，可视化对比。

---

## 5. Eval 集成（未来）

Langfuse 支持内置 Eval，可以接入 LLM-as-Judge 结果：

```python
from langfuse import Langfuse

lf = Langfuse(...)

# 在 evaluation_agent 跑完后
score = lf.score(
    trace_id=trace_id,
    name="quality_score",
    value=eval_output["score"],
    comment=eval_output.get("suggested_fix", ""),
)
```

这样在 Langfuse UI 上能看到每条 trace 的质量评分。

---

## 6. 常见问题

### Q1: Langfuse 连接失败

**症状**：日志报 `Langfuse trace 创建失败`

**排查**：

```bash
# 1. 检查 Langfuse 是否启动
docker compose ps langfuse

# 2. 测试连通性
curl http://localhost:3000/api/public/health

# 3. 检查 API Key
echo $LANGFUSE_PUBLIC_KEY
echo $LANGFUSE_SECRET_KEY
```

**解决**：

- Langfuse 未启动：`docker compose up -d langfuse`
- API Key 错误：重新生成
- 网络问题：检查 docker network

### Q2: Trace 没出现在 Langfuse

**原因**：未调用 `flush()`

**解决**：

- Worker 进程退出前调用 `flush_langfuse()`
- 或配置 Langfuse SDK 的 batch flush

### Q3: Token 数量不准

**原因**：Anthropic API 返回的 usage 字段可能不包含 cache tokens

**解决**：手动累加 input + output tokens

### Q4: 想关闭 Langfuse

```bash
LANGFUSE_ENABLED=false
docker compose restart api worker-light worker-heavy
```

代码中 `get_langfuse()` 会返回 None，自动跳过上报。

---

## 7. 生产部署提示

### 7.1 Langfuse 生产化

- 不要用 docker-compose 内置的 sqlite，用 PostgreSQL（已配置）
- 用 S3 / GCS 存 Langfuse 上传的截图 / 文件
- 配置 Langfuse SSO（OIDC）
- NEXTAUTH_SECRET 和 SALT 用 `openssl rand -hex 32` 生成

### 7.2 高可用

Langfuse 本身无状态（除 DB），可以水平扩展：

```yaml
langfuse:
  image: langfuse/langfuse:latest
  deploy:
    replicas: 2
```

但 DB 是 PostgreSQL，需要做好备份。

### 7.3 数据保留

Langfuse 的 trace 数据默认保留 30 天，可配置：

```env
LANGFUSE_RETENTION_DAYS=90
```

---

## 附录：完整 Langfuse 配置示例

```python
# app/services/tracing.py - 完整配置参考

from langfuse import Langfuse

lf = Langfuse(
    public_key="pk-lf-xxx",
    secret_key="sk-lf-xxx",
    host="http://langfuse:3000",  # docker 网络内用服务名
    release="adagentflow@1.0.0",   # 标识版本
    debug=False,                    # 生产关闭
)

# 创建 trace
trace = lf.trace(
    id="trace_1720600000_xxx",
    name="adagentflow_task",
    user_id="anonymous",            # 未来从 token 取
    metadata={"platform": "TikTok"},
    tags=["production"],
)

# 创建 generation（LLM 调用）
generation = trace.generation(
    name="script_generation",
    model="MiniMax-M3",
    input=[{"role": "user", "content": user_prompt}],
    output=llm_response_content,
    usage={
        "input": input_tokens,
        "output": output_tokens,
        "total": input_tokens + output_tokens,
    },
    metadata={"prompt_version": "v1.2"},
)

# 评分
trace.score(name="quality", value=87)

# 结束
trace.end()
```