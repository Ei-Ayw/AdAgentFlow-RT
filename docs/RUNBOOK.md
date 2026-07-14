# AdAgentFlow 运维手册 (RUNBOOK)

> 本文档面向运维 / SRE / 工程师，描述部署、升级、监控、告警、故障排查、Dashboard 二次开发。

---

## 1. 部署

### 1.1 本地开发部署

```bash
# 克隆
git clone https://github.com/your-org/AdAgentFlow.git
cd AdAgentFlow

# 复制环境变量
cp .env.example .env

# 一键拉起全部服务
docker compose up -d

# 查看日志
docker compose logs -f api
docker compose logs -f worker-light

# 停止
docker compose down

# 完全重置（含数据）
docker compose down -v
```

### 1.2 生产 K8s 部署（提示）

> ⚠️ 当前 `docker-compose.yml` 面向单机 / 开发；生产 K8s 需要做以下改造。

```mermaid
flowchart LR
    subgraph K8s["Kubernetes Cluster"]
        subgraph NS["Namespace: adagentflow"]
            ING[Ingress<br/>nginx-ingress]
            SVC[Service: api]
            API[Deployment: api<br/>replicas: 2-4<br/>HPA: CPU>70%]
            LW[Deployment: worker-light<br/>replicas: 3-10<br/>HPA: queue depth]
            HW[Deployment: worker-heavy<br/>replicas: 1-3]
            DS[StatefulSet: postgres<br/>replicas: 1 + PVC]
            RD[Deployment: redis<br/>replicas: 1]
            MQ[StatefulSet: rabbitmq<br/>replicas: 3 (cluster)]
            LF[Deployment: langfuse<br/>replicas: 2]
        end
    end

    ING --> SVC --> API
    API --> DS & RD & MQ
    LW & HW --> DS & RD & MQ
    LF --> DS
```

**关键改造点**：

1. **RabbitMQ** → 用 RabbitMQ Cluster Operator，开 `cluster_partition_handling=pause_minority`
2. **PostgreSQL** → 用云厂商托管 RDS 或 Zalando Postgres Operator；开 `pg_stat_statements` 监控慢查询
3. **Redis** → 用云厂商托管 ElastiCache / 阿里云 Redis；禁 `KEYS *`，改用 SCAN
4. **API & Worker** → 用 KEDA 根据 RabbitMQ 队列深度自动扩缩容
5. **ConfigMap / Secret** → 把 `.env` 内容塞进 Secret；JWT、DB password 单独管理
6. **PVC** → postgres_data / redis_data / rabbitmq_data 都需要 PersistentVolume
7. **NetworkPolicy** → 默认禁所有入站，只允许 API 接 Ingress、Worker 接 RabbitMQ
8. **PodDisruptionBudget** → API 至少 1 副本可用，Worker 至少 2 副本可用

### 1.3 健康检查端点

| 端点 | 说明 |
|------|------|
| `GET /live` | 仅检查 API 进程存活 |
| `GET /ready` | 检查 PostgreSQL、Redis、RabbitMQ，失败返回 503 |
| `GET /health` | 兼容入口，语义等同 `/ready` |
| `GET /metrics` | Prometheus 指标 |
| `GET /api/v1/dashboard/health-check` | 全组件健康检查 |
| RabbitMQ Management UI | http://localhost:15672 |
| Langfuse UI | http://localhost:3000 |

---

## 2. 升级与回滚

### 2.1 升级流程

```bash
# 1. 拉取最新代码
git pull origin main

# 2. 备份数据库（生产必做）
pg_dump -h localhost -U adagent adagentflow > backup_$(date +%Y%m%d).sql

# 3. 执行版本化迁移
alembic upgrade head

# 4. 滚动重启（先 Worker 后 API，避免消息丢失）
docker compose up -d --no-deps worker-light
docker compose up -d --no-deps worker-heavy
sleep 30  # 等 Worker 处理完积压
docker compose up -d --no-deps api

# 5. 验证
curl http://localhost:8000/health
```

### 2.2 回滚流程

```bash
# 1. 回滚代码
git checkout <previous_tag>
docker compose up -d --build

# 2. 若涉及 schema 变更，恢复 DB
psql -h localhost -U adagent adagentflow < backup_20260101.sql

# 3. 重启 RabbitMQ（队列里可能有不兼容的消息）
docker compose restart rabbitmq
```

### 2.3 数据库迁移

生产设置 `DATABASE_AUTO_CREATE=false`，只允许 Alembic 修改 Schema：

```bash
alembic current
alembic heads
alembic upgrade head
```

---

## 3. 监控与告警

### 3.1 关键指标

| 指标 | 计算方式 | 告警阈值 |
|------|---------|---------|
| 端到端成功率 | `success / total` | < 90% 黄色，< 80% 红色 |
| JSON 解析失败率 | `json_failures / llm_calls` | > 10% 黄色，> 20% 红色 |
| 死信率 | `dead_letter / total` | > 3% 黄色，> 5% 红色 |
| 平均任务耗时 | `avg(finished - created)` | > 30s 黄色，> 60s 红色 |
| Worker 队列深度 | RabbitMQ `messages_ready` | > 1000 黄色，> 5000 红色 |
| DB 连接池使用率 | `checkedout / (pool_size + max_overflow)` | > 80% 黄色 |
| Redis 内存 | `INFO memory` `used_memory` | > 80% of maxmemory 黄色 |

### 3.2 Prometheus 集成

API 已通过 `/metrics` 暴露 Outbox 发布结果与各状态积压量。告警规则位于
`deploy/prometheus/adagentflow-rules.yml`。RabbitMQ 规则要求部署 RabbitMQ Prometheus exporter。

### 3.3 日志位置

- **容器内**：`/app/logs/adagentflow_YYYY-MM-DD.log`
- **容器外**：通过 `docker compose logs` 查看 stdout
- **格式**：生产默认 JSON，包含 `service/instance/task_id/step_id/message_id/trace_id/execution_id`；本地可设置 `LOG_FORMAT=text`
- **rotation**：100MB 自动 rotate，保留 30 天

### 3.4 推荐告警规则（PromQL）

```yaml
groups:
  - name: adagentflow
    rules:
      - alert: AdAgentFlowHighJsonFailure
        expr: rate(adagentflow_json_failures_total[5m]) > 0.2
        for: 10m
        labels: { severity: warning }
        annotations:
          summary: "JSON 解析失败率 > 20%"

      - alert: AdAgentFlowDeadLetterSpike
        expr: rate(adagentflow_dead_letters_total[5m]) > 0.05
        for: 5m
        labels: { severity: critical }
        annotations:
          summary: "死信率 > 5%"

      - alert: AdAgentFlowWorkerQueueBacklog
        expr: rabbitmq_queue_messages_ready{queue=~"ad_task\\..*"} > 1000
        for: 10m
        labels: { severity: warning }
        annotations:
          summary: "Worker 队列堆积"
```

---

## 4. 常见故障排查

告警处理统一顺序：确认影响范围 → 暂停接流量/扩容止损 → 保留日志与指标证据 → 恢复服务 → 补录时间线和根因。不要在未备份时删除队列或 Outbox 数据。

### API 不可用

1. 对比 `/live` 与 `/ready`：前者失败是进程问题，只有后者失败通常是依赖问题；
2. 查看 readiness 返回的 `checks`，定位 PostgreSQL、Redis 或 RabbitMQ；
3. 若依赖大面积异常，先从负载均衡摘除实例，不要反复重启导致重试风暴；
4. 恢复后确认 Outbox、工作队列和死信没有持续增长。

### Outbox 积压

1. 查询 `outbox_events` 中 `pending/failed/publishing` 数量、最早创建时间和 `last_error`；
2. 检查 `worker-outbox` 日志及 RabbitMQ readiness；
3. 若 RabbitMQ 已恢复，先单副本观察补发，再逐步扩容；
4. 不要直接把记录改成 `published`，否则会永久丢消息。

### Outbox exhausted

1. 按 `last_error` 聚类，确认是认证、拓扑不一致、网络还是坏消息；
2. 修复根因后将选定事件恢复为 `failed`、清空锁字段并降低尝试次数；
3. 由 Outbox Worker 补发并观察消费端幂等；
4. 记录重复投递数和最终业务状态。

### 死信增长

1. 按 `failure_reason/step_id/model_name/prompt_version` 聚类；
2. 基础设施错误优先恢复依赖，Schema/内容错误检查 Prompt 和 Repair；
3. 批量恢复前先用一条任务验证；
4. 未确认根因前不要清空 DLQ。

### 4.1 Worker 不消费

**症状**：任务提交后一直停在 `queued` 状态，Dashboard 不更新。

**排查步骤**：

```bash
# 1. 检查 Worker 容器是否在运行
docker compose ps worker-light

# 2. 查看 Worker 日志
docker compose logs --tail=100 worker-light

# 3. 检查 RabbitMQ 队列
# 浏览器打开 http://localhost:15672（密码从本地 Secret/.env 获取）
# 看 ad_task.* 队列的 messages_ready 是否 > 0

# 4. 检查队列消费者数量
docker exec adagentflow-rabbitmq rabbitmqctl list_queues name consumers
# 如果 consumers = 0，说明 Worker 没绑定上

# 5. 检查网络
docker exec adagentflow-worker-light ping rabbitmq

# 6. 重启 Worker
docker compose restart worker-light worker-heavy
```

**常见原因**：

- Worker 进程崩溃但 Docker 没退出（OOM Killer）
- RabbitMQ 连接断开，aio-pika 自动重连失败
- 队列声明参数不一致（durability / DLX 不匹配）

### 4.2 数据库连接耗尽

**症状**：API 返回 `OperationalError: FATAL: too many connections`，Worker 报 `QueuePool limit`。

**排查步骤**：

```sql
-- 1. 查看当前连接数
SELECT count(*) FROM pg_stat_activity;

-- 2. 查看最久的连接
SELECT pid, usename, application_name, state, query_start
FROM pg_stat_activity
ORDER BY query_start ASC
LIMIT 20;

-- 3. 杀掉长查询
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
WHERE state = 'active' AND query_start < now() - interval '5 minutes';
```

```bash
# 4. 增加连接池（修改 .env）
DB_POOL_SIZE=40
DB_MAX_OVERFLOW=80
docker compose restart api worker-light worker-heavy
```

**预防**：

- 监控 `pg_stat_activity` 的连接数
- API 用 `Depends(get_db)` 确保每次请求关闭 Session
- Worker 用 `session_scope()` context manager

### 4.3 Redis 内存爆

**症状**：`OOM command not allowed when used memory > 'maxmemory'` 或响应缓慢。

**排查步骤**：

```bash
# 1. 查看内存使用
docker exec adagentflow-redis redis-cli INFO memory

# 2. 查看 key 数量
docker exec adagentflow-redis redis-cli DBSIZE

# 3. 查看大 key
docker exec adagentflow-redis redis-cli --bigkeys

# 4. 查看幂等键数量
docker exec adagentflow-redis redis-cli KEYS "idempotent:*" | wc -l
```

**解决**：

```bash
# 方案 1: 增加内存（修改 docker-compose.yml）
command: ["redis-server", "--appendonly", "yes", "--maxmemory", "1gb", "--maxmemory-policy", "allkeys-lru"]

# 方案 2: 缩短 TTL（修改 .env）
REDIS_IDEMPOTENT_TTL=3600  # 1 小时

# 方案 3: 清理过期 key（自动，不用手动）
docker exec adagentflow-redis redis-cli FLUSHDB
```

### 4.4 LLM 超时

**症状**：Dashboard 显示大量 `MODEL_TIMEOUT` 失败，`failure_top_5` 排第一。

**排查步骤**：

```bash
# 1. 测试 LLM 连通性
curl -X POST $ANTHROPIC_BASE_URL/v1/messages \
  -H "Authorization: Bearer $ANTHROPIC_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model": "MiniMax-M3", "max_tokens": 100, "messages": [{"role": "user", "content": "hi"}]}'

# 2. 查看 LLM 客户端日志
docker compose logs api | grep "LLM"

# 3. 增加超时（修改 .env）
LLM_TIMEOUT=60

# 4. 切换模型
ANTHROPIC_DEFAULT_HAIKU_MODEL=claude-haiku-4-5
```

**预防**：

- 在 `LLMClient` 加 retry + exponential backoff
- 监控 `MODEL_TIMEOUT` 占比，超过阈值触发告警
- 配置 fallback 模型

### 4.5 死信任务不处理

**症状**：Dashboard 的 `unresolved_dead_letters` 列表越来越长。

**排查步骤**：

```bash
# 1. 查看死信列表
curl http://localhost:8000/api/v1/dead-letters/

# 2. 查看单条死信详情
curl http://localhost:8000/api/v1/dead-letters/123

# 3. 手动接管
curl -X POST http://localhost:8000/api/v1/dead-letters/task_xxx/resume

# 4. 批量解决（标记为已处理）
curl -X POST http://localhost:8000/api/v1/dead-letters/123/resolve
```

### 4.6 任务一直停留在 running

**症状**：Worker 重启后，任务卡在 running 不动。

**原因**：Worker 崩溃前没把状态回滚到 failed。

**解决**：

```sql
-- 手动重置超过 10 分钟仍 running 的 step
UPDATE task_steps
SET status = 'failed',
    finished_at = now(),
    error_message = 'Worker crashed, reset manually'
WHERE status = 'running'
  AND started_at < now() - interval '10 minutes';

-- 重置 task
UPDATE tasks
SET status = 'retrying'
WHERE status = 'running'
  AND updated_at < now() - interval '10 minutes';

-- 重新派发（走 orchestrator）
```

### 4.7 重复消息告警

**症状**：`idempotent_count` 持续增长。

**排查**：

```bash
# 查看幂等键总数
docker exec adagentflow-redis redis-cli KEYS "idempotent:*" | wc -l

# 单个 key 的 TTL
docker exec adagentflow-redis redis-cli TTL "idempotent:task_xxx:script_generation"
```

**正常**：幂等键数量 = 当前 running + 最近 24h 完成的任务数。

**异常**：幂等键数量 >> 任务总数，说明有重复消息堆积或 TTL 没生效。

---

## 5. Dashboard 二次开发

### 5.1 Dashboard 结构

```
app/dashboard/static/
├── index.html        # 主页面
├── app.js            # 前端逻辑
└── style.css         # 样式
```

`app/dashboard/static.py` 是一个简单的静态文件服务，挂在 `/dashboard`。

### 5.2 添加新指标

**Step 1**：在 `app/api/dashboard_router.py` 添加新 endpoint：

```python
@router.get("/custom-metric")
def custom_metric(db: Session = Depends(get_db)):
    return {"value": 42}
```

**Step 2**：在 `app/dashboard/static/index.html` 添加卡片：

```html
<div class="card">
  <h3>自定义指标</h3>
  <div id="custom-metric-value">--</div>
</div>
```

**Step 3**：在 `app/dashboard/static/app.js` 添加 fetch：

```javascript
fetch('/api/v1/dashboard/custom-metric')
  .then(r => r.json())
  .then(data => {
    document.getElementById('custom-metric-value').textContent = data.value;
  });
```

### 5.3 接入 Grafana（推荐）

1. 启动 Prometheus 抓取 `/metrics` 端点
2. 配置 Prometheus 抓取 `prometheus.yml`
3. Grafana 添加 Prometheus datasource
4. 导入 [AdAgentFlow Dashboard JSON](#) （TODO: 提供 JSON 模板）

---

## 6. 备份与恢复

### 6.1 数据库备份

```bash
# 每日定时备份
0 2 * * * pg_dump -h localhost -U adagent adagentflow | gzip > /backup/adagentflow_$(date +\%Y\%m\%d).sql.gz

# 保留 30 天
find /backup -name "adagentflow_*.sql.gz" -mtime +30 -delete
```

### 6.2 Redis 备份

RDB 默认开启在 `redis_data` volume，定时用 `cron` 拷贝。

### 6.3 RabbitMQ 备份

```bash
# 导出队列定义
docker exec adagentflow-rabbitmq rabbitmqctl export_definitions /tmp/definitions.json
docker cp adagentflow-rabbitmq:/tmp/definitions.json ./rabbitmq_definitions_$(date +%Y%m%d).json
```

---

## 7. 安全建议

### 7.1 当前状态

- `.env.example` 只保留占位符，真实值必须通过 Secret 注入
- RabbitMQ 和 PostgreSQL 禁止使用仓库历史中的旧密码
- ⚠️ API 无鉴权（开发用），生产必须加 API Key / JWT
- ⚠️ CORS 设为 `*`，生产应限制 origin

### 7.2 生产 checklist

- [ ] 替换所有默认密码
- [ ] API 加 API Key 中间件
- [ ] 启用 HTTPS（用 nginx + certbot）
- [ ] 数据库连接用 SSL
- [ ] RabbitMQ 用 vhost 隔离
- [ ] 限制 Dashboard 只能内网访问
- [ ] 定期轮换 Langfuse / Anthropic key
- [ ] 启用 audit log

---

## 8. 联系与升级

- 代码仓库 Issues：报告 bug 与 feature request
- 内部 Slack：#adagentflow-ops
- 值班 oncall：每周轮换，详见 oncall 排班表

每次代码变更后请更新本 RUNBOOK 的对应章节。
