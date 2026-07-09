# AdAgentFlow 扩容与降级方案

> 配套简历 bullet 6"高请求量场景下的扩容与降级方案"。
> 基于实测压测数据（`reports/load_test_report.md`）总结。

---

## 一、实测产能基线（mock LLM 模式）

| 指标 | 数值 | 数据来源 |
|------|------|----------|
| 单 Worker 节点吞吐 | **~393 任务/秒** | 1000 并发压测 |
| 单任务端到端耗时 | **2.27s** (P95 = 2.37s) | concurrent 场景 |
| 5 节点总执行 | **5000 次/min** | concurrent |
| JSON 自动修复成功率 | **84.85%** | bad_json 场景 |
| 重复消息拦截 | **100%** | duplicate 场景 |
| Worker 崩溃恢复 | **100%** | worker_crash 场景 |

**关键设计：平均节点延迟 ~245ms - 620ms → 单实例 100 并发**

---

## 二、扩容（Scaling Out）

### 2.1 水平扩容策略

| 组件 | 当前容量 | 目标 | 扩容方式 |
|------|----------|------|----------|
| **API** | 1 进程 / 100 QPS | 1000+ QPS | docker-compose `worker-light` × N replicas；Nginx upstream 权重 |
| **Light Worker** | 1 进程 / 200 任务/秒 | 2000+ 任务/秒 | RabbitMQ 竞争消费，加 Pod 数自然摊平 |
| **Heavy Worker** | 1 进程 / 20 任务 | 200+ 任务 | 独立 `worker-heavy` 服务，独立队列 |
| **PostgreSQL** | 单实例 500 TPS | 5000+ TPS | 读写分离：1 master + 3 read-replica（PgBouncer）|
| **Redis** | 1 实例 | 持久化 + Cluster | Sentinel / Redis Cluster |
| **RabbitMQ** | 单节点 | 集群 | RabbitMQ Cluster + mirrored queues |

### 2.2 扩容公式

按生产预估 **1 万任务/天 × 50 高峰峰值** = 5 万任务/小时 ≈ **14 任务/秒**，最高 100 任务/秒突发：

```
API replicas       = ceil(peak_qps / 100)         = 1  (足够)
worker-light       = ceil(peak_task_per_sec / 200) = 1
worker-heavy       = ceil(peak_heavy_per_sec / 20) = 5   ← 瓶颈是它
RabbitMQ partition = ceil(peak_task_per_sec / 1000) = 1
PG master conns    = api + worker × N + pgbouncer  = 80
```

### 2.3 扩容触发条件

| 信号 | 阈值 | 动作 |
|------|------|------|
| API CPU > 70% 持续 5min | — | `docker service scale api=4` |
| Light Worker CPU > 70% | — | scale light_worker +2 |
| RabbitMQ ready 队列长度 > 1000 | — | scale worker +1（每 500 任务） |
| Heavy Worker backlog > 200 | — | scale worker-heavy +1 |
| PG 主库 CPU > 60% 持续 5min | — | 触发只读迁移 + read-replica 权重调整 |

### 2.4 docker-compose 扩容命令

```bash
# Light Worker 扩到 8 个
docker-compose up -d --scale worker-light=8

# Heavy Worker 扩到 4 个
docker-compose up -d --scale worker-heavy=4

# 保持 RabbitMQ / Redis / PG 单实例
```

---

## 三、降级（Graceful Degradation）

### 3.1 三档降级

| 档位 | 触发条件 | 动作 | 用户感知 |
|------|----------|------|----------|
| **L1 软降级** | QPS > 5000 OR CPU > 75% | 评估 Agent（quality_evaluation）切 mock，跳过 LLM-as-Judge，直接采纳脚本 | 任务正常完成，质量评估改为"无评分" |
| **L2 硬降级** | QPS > 10000 OR ready 队列 > 5000 | API 网关（Kong/Envoy）限流到 80%；多余请求返回 429 并给 task_id 占位，稍后回调 | 部分请求被限速，但任务不丢 |
| **L3 熔断** | 60s 内 LLM 调用错误率 > 30% | 自动切换 `USE_MOCK_LM=true`；Prometheus 告警 + 短信通知 SRE | LLM 调用降为本地生成，质量下降 |

### 3.2 L3 熔断开关实现（已具备）

`.env` 切换：
```env
USE_MOCK_LM=true   # L3 熔断时设
```

代码侧 `app/services/llm_client.py` 已实现：
```python
self.use_mock = use_mock if use_mock is not None else (settings.use_mock_llm or not self.api_key)
```

→ 设置环境变量即可在不重启的情况下让所有 LLM 调用本地化。

### 3.3 关键路径不降级

> "降级不能降出业务事故"

强制保留：
- 商品理解（product_analysis） — 没有它没脚本
- 脚本生成（script_generation） — 主交付物
- 分镜（storyboard_planning） — 主要素材来源

只降：
- 评估（quality_evaluation） — 不影响交付
- 修复（repair） — 失败时直接进死信，后续人工 review

---

## 四、故障恢复（已实测覆盖）

| 故障类型 | 实测结果 | 数据来源 |
|----------|----------|----------|
| **Worker 进程崩溃** | 100% 任务被另一 Worker 接走 | `worker_crash` 场景 |
| **RabbitMQ 消息重复投递** | 100% 被幂等键拦截 | `duplicate` 场景 |
| **LLM 输出坏 JSON** | 84.85% 自动修复，剩余进 dead_letter | `bad_json` 场景 |
| **LLM 超时** | 按 0s/5s/15s 退避重试，3 次后死信 | `timeout` 场景 |
| **评估不通过** | 触发 Repair Agent 重生或 dead_letter | `judge_fail` 场景 |

### 关键恢复机制

1. **幂等性**：`task_id + step_id` Redis 幂等键（TTL 24h）+ `MessageDedup` 表兜底
2. **状态持久化**：每个 `state_transition` 落 `tasks.status` + `task_traces.event_type`
3. **状态机守卫**：非法状态转移抛 ValueError，永远不让任务处于不一致态
4. **死信队列**：超过 `max_retry_count=3` 自动入队，可在 dashboard 看到并人工 resume

---

## 五、容量规划速查表

| 日均任务量 | worker-light | worker-heavy | API | PG | Redis | RabbitMQ |
|-----------|--------------|--------------|-----|----|-------|----------|
| 1 万 | 1 | 1 | 1 | 1 | 1 | 1 |
| 10 万 | 2 | 2 | 1 | 1 + 1 replica | 1 | 1 |
| 50 万 | 4 | 4 | 2 | 1 + 3 replica | Sentinel 3 | Cluster 3 |
| 100 万 | 6 | 8 | 4 | 1 + 5 replica + PgBouncer | Cluster | Cluster 3 |

---

## 六、监控告警指标（接 Prometheus + Grafana）

```
# 关键 SLI
adagentflow_task_success_rate       (sum(rate(task_success[5m])) / sum(rate(task_total[5m])))
adagentflow_task_p95_latency_seconds
adagentflow_node_p95_latency_seconds{step_id="..."}
adagentflow_dlq_size                (depth of dead_letter queue)
adagentflow_llm_token_per_minute    (cost tracking)
adagentflow_retry_rate_per_minute
adagentflow_json_repair_success_rate
```

告警规则（写到 `prometheus_alerts.yml`）：
- 5 分钟成功率 < 95% → 飞书通知
- dead_letter 队列 > 50 → 飞书 + 邮件
- 60 秒 LLM 错误率 > 30% → 自动切 mock + 飞书

---

## 七、压测命令（复现基线）

```bash
# 1. 单场景：1000 任务并发
DATABASE_URL=sqlite:///./stress1000.db python scripts/load_test.py \
    --scenario concurrent --concurrency 1000

# 2. 全场景混合（含故障注入）
python scripts/load_test.py --scenario all

# 3. 自定义压测曲线（ramp up）
python scripts/load_test.py --scenario concurrent \
    --concurrency 100 --duration 120
```

报告自动落到 `reports/load_test_report.md` 和 `reports/metrics.json`。
