# 真实基础设施负载基线

- 日期：2026-07-14
- 环境：本机 Docker，PostgreSQL 16、Redis 7、RabbitMQ 3.13
- 负载：每个组件 200 次操作，并发 20
- 范围：只测基础设施，不包含 LLM、业务内容质量或完整任务端到端延迟

| 组件与操作 | 错误 | 吞吐 ops/s | P50 | P95 | P99 | Max |
|---|---:|---:|---:|---:|---:|---:|
| PostgreSQL Outbox 单事务写入 | 0 | 1680.42 | 5.19 ms | 62.58 ms | 64.25 ms | 65.71 ms |
| Redis SET/GET/DELETE | 0 | 7853.75 | 1.61 ms | 9.40 ms | 9.76 ms | 9.82 ms |
| RabbitMQ publisher confirm | 0 | 9203.27 | 1.94 ms | 2.88 ms | 3.17 ms | 3.24 ms |

## 解读

PostgreSQL P95 明显高于 P50，是当前基础设施路径里最值得继续观察的部分；该数字同时包含本机 Docker、线程调度和逐事务提交开销。它不能直接外推生产容量，也不能代表完整 Agent 吞吐。

可复现命令：

```bash
docker compose -f docker-compose.integration.yml up -d --wait
DATABASE_URL=postgresql://adagent:<password>@localhost:15432/adagentflow alembic upgrade head
DATABASE_URL=postgresql://adagent:<password>@localhost:15432/adagentflow \
REDIS_URL=redis://localhost:16379/0 \
RABBITMQ_URL=amqp://adagent:<password>@localhost:25672/adagentflow \
python scripts/infrastructure_load_test.py --operations 200 --concurrency 20
docker compose -f docker-compose.integration.yml down -v
```

下一轮应分别改变并发 1/10/20/50、记录 PostgreSQL 连接池占用，并单独运行真实 LLM 小样本；真实 LLM 测试涉及费用，不纳入默认 CI。
