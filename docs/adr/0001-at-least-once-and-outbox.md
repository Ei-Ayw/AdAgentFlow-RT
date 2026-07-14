# ADR-0001：At-least-once 与 Transactional Outbox

- 状态：已采纳
- 日期：2026-07-14

## 背景

工作流需要同时更新 PostgreSQL 状态并向 RabbitMQ 派发下一节点。两者无法共享本地事务，直接“先写库再发消息”存在数据库成功、消息发布失败的丢任务窗口。

## 决策

业务状态与 Outbox 事件在同一 PostgreSQL 事务提交。提交后先立即发布，失败则由独立 Outbox Worker 认领补发。交付语义定义为 at-least-once，消费者依靠数据库节点状态和 Redis owner-token 执行租约实现业务结果等价一次。

不宣称分布式 exactly-once。发布成功后、标记 Outbox 成功前崩溃仍可能重复投递，这是设计允许的行为。

## 代价

- 增加 Outbox 表、扫描 Worker、积压监控和清理策略；
- 消费者必须始终保持幂等；
- 极端情况下会重复调用下游，因此执行状态检查必须早于模型调用。

## 重新评估条件

当事件规模导致轮询表成为瓶颈，或需要跨多个服务编排补偿时，再评估 CDC、Kafka Connect 或可靠工作流引擎。
