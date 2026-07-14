# AdAgentFlow 故障矩阵

> 目标不是证明“永不失败”，而是明确每个故障窗口是否丢任务、是否可能重复，以及由谁恢复。

| 故障点 | 预期语义 | 恢复机制 | 当前验证 |
|---|---|---|---|
| 重复消息同时到达 | 最多一个 Worker 进入模型调用 | Redis owner-token 短租约 + TaskStep 状态 | 单元测试；真实 Redis 测试 |
| Worker 获取锁后硬退出 | 租约到期后允许重跑 | Redis TTL | 真实子进程 `SIGKILL` 已通过 |
| 可重试基础设施异常 | 当前消息不被静默 ACK | 首次 requeue，再次进入 DLX | Worker 单元测试 |
| 延迟重试期间 Worker 重启 | 重试不会因进程退出消失 | RabbitMQ TTL + DLX 持久化队列 | 单元测试；真实 RabbitMQ 测试 |
| 业务事务回滚 | 不应留下下一节点消息 | 同事务 Outbox | Outbox 回滚测试 |
| 数据库成功、发布前进程退出 | 任务不丢失，稍后补发 | Outbox Worker | 真实子进程 `SIGKILL` 已通过 |
| 发布成功、Outbox 标记前退出 | 允许重复消息，不允许重复业务结果 | at-least-once + 消费幂等 | 设计验证；待进程注入实验 |
| Repair 成功 | 写回目标节点并使下游失效 | Schema 校验 + 下游重置 | 编排测试 |
| Repair/评估不收敛 | 有界退出，不无限调用模型 | 最大重试 + 死信/人工审核 | 单元路径已覆盖；待 E2E |
| Outbox 连续失败 | 达到上限后显式暴露 | `exhausted` 状态 + Prometheus 指标 | 单元测试 |
| PostgreSQL 不可用 | API 不接流量 | `/ready` 返回 503 | API 测试 |
| Redis/RabbitMQ 不可用 | API 不接流量并暴露依赖状态 | `/ready` 返回 503 | API 测试 |

## 仍需执行的注入实验

- 在模型调用中、数据库提交前和消息 ACK 前分别发送 `SIGKILL`（锁后退出、提交后发布前退出已自动化）；
- 使用 Toxiproxy 注入 Redis、RabbitMQ、PostgreSQL 延迟和断连；
- 压满数据库连接池，记录恢复时间和积压变化；
- 注入乱序、过期和大体积消息；
- 对真实 LLM 注入超时、429、坏 JSON 和高延迟。

每次实验记录：Git commit、环境配置、注入时间、最终任务状态、重复 execution 数、恢复耗时、队列峰值和是否需要人工操作。
