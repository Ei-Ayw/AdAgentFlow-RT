# AdAgentFlow 压测 + 故障模拟

> 面向电商短视频广告生成的多 Agent 长任务可靠性框架压测脚本集合。

## 文件结构

```
scripts/
├── load_test.py              # CLI 入口，支持 --scenario / --concurrency
├── failure_scenarios.py      # 6 个故障模拟场景实现
├── report_generator.py       # 汇总 metrics 输出 Markdown + JSON + CSV
├── helpers/
│   ├── mock_infra.py         # 进程内 Mock Redis / DB / Queue + 故障注入开关
│   ├── metrics_collector.py  # 指标聚合（成功率 / P95 / 节点级统计）
│   └── scenario_base.py      # 通用 worker 模拟器 / 任务驱动
├── scenarios/
│   └── run_all.sh            # 一键跑完 6 个场景
└── README.md                 # 本文件

reports/                      # 输出目录（跑完后自动生成）
├── load_test_report.md       # 人类可读 Markdown 报告（可直接贴简历）
├── metrics.json              # 机器可读 JSON
└── throughput_curve.csv      # 场景1的吞吐曲线
```

## 快速开始

### 单个场景

```bash
# 场景 1: 并发压测（200 个任务）
python scripts/load_test.py --scenario concurrent --concurrency 200

# 场景 2: JSON 异常模拟（注入 70% 坏 JSON）
python scripts/load_test.py --scenario bad_json --concurrency 50 --bad-json-rate 0.7

# 场景 3: Worker 崩溃模拟（在第 50 个任务时崩溃）
python scripts/load_test.py --scenario worker_crash --concurrency 100 --crash-at 50

# 场景 4: 重复消息投递（每条消息重复 2 次）
python scripts/load_test.py --scenario duplicate --concurrency 100 --replication 2

# 场景 5: 模型超时（30% 注入超时）
python scripts/load_test.py --scenario timeout --concurrency 100 --timeout-rate 0.3

# 场景 6: 评估不通过 → 修复 agent
python scripts/load_test.py --scenario judge_fail --concurrency 50
```

### 一键跑全部

```bash
bash scripts/scenarios/run_all.sh

# 自定义并发数
CONCURRENCY=200 bash scripts/scenarios/run_all.sh
```

### 不依赖 Docker

所有脚本默认使用 `scripts/helpers/mock_infra.py` 中的进程内 Mock 实现：

- **Mock Redis** — 字典实现的 SETNX / EXPIRE / KEYS
- **Mock Database** — 内存版 task / step / dead_letter 表
- **Mock Queue** — 内存版 RabbitMQ topic exchange
- **Mock LLM** — `app.services.llm_client` 的 mock 路径，按注入开关返回坏 JSON / 超时 / 评估失败

不需要启动 `docker-compose up`，随时 `python scripts/load_test.py` 直接跑。

## 场景设计详解

### 场景 1: 正常并发压测

- 并发提交 N 个任务 (默认 N = 50)
- 等所有任务走完 5 个 Agent 节点
- 记录端到端成功率、平均耗时、平均重试次数、JSON 失败率
- 输出吞吐量曲线 (CSV)

### 场景 2: JSON 异常模拟

- 设置 `bad_json_rate = 0.7`，70% 的 LLM 输出会被注入坏 JSON
- 验证：
  - `quick_json_repair`（本地补全右括号 / 去 markdown）能否修复
  - `build_repair_prompt` + LLM 二次修复能否修复
  - 失败次数是否被统计到 `failure_reason = JSON_PARSE_ERROR`
  - 最终修复成功率（修复后能跑通 = 成功）

### 场景 3: Worker 崩溃模拟

- 跑 N 个任务，在第 `crash_at` 个时模拟 worker 崩溃
- 验证：
  - 任务是否停留在 `running` 状态（生产里要靠 supervisor 重启拉起）
  - 重启后任务是否被新 worker 接管
  - 幂等键是否生效，避免重复写入 `task_steps`

### 场景 4: 重复消息投递

- 每个 task 投递 `replication` 条相同消息
- 验证：
  - `idempotent:{task_id}:{step_id}` 键是否拦截第二条消息
  - 同一 `(task_id, step_id)` 不会重复写入数据库
  - 不会出现重复 step 行

### 场景 5: 模型超时

- 设置 `timeout_rate = 0.3`，30% LLM 调用抛 `LLMTimeoutError`
- 验证：
  - 指数退避（0s / 5s / 15s）是否生效
  - 超过 `max_retry_count = 3` 是否进死信队列

### 场景 6: 评估不通过 → 修复 agent

- 强制让 evaluator 输出 `passed = false`、`risk_level = medium`
- 验证：
  - orchestrator 是否触发 repair agent
  - `repair_triggered` 计数是否正确

## 输出报告

跑完后会生成 `reports/load_test_report.md`，包含：

1. **总览表** — 各场景的端到端成功率、平均耗时、吞吐
2. **节点级成功率** — product_analysis / script_generation / storyboard_planning / material_suggestion / quality_evaluation 每个 Agent 的成功率
3. **详细场景数据** — 每个场景的关键指标
4. **故障统计汇总** — JSON 失败、dead_letter、repair 触发、幂等拦截
5. **简历可贴片段** — 已经组织好可直接贴到简历项目经历的格式

## 简历用法

`reports/load_test_report.md` 末尾的"简历可贴片段"已经按 5 个场景组织好：

```
## 压测报告（生产环境模拟）

### 场景 1: 并发压测
- 并发: 200 任务
- 端到端成功率: 96.5% (193/200)
- 平均耗时: 14.7s
- P95 耗时: 28.3s
- 平均重试次数: 0.5
- 端到端吞吐量: 13.6 任务/秒

### 场景 2: JSON 解析失败压力
- 注入坏 JSON 任务: 50 个
- quick repair 修复成功率: 68% (34/50)
- LLM repair 修复成功率: 92% (46/50)
- 最终修复成功率: 96% (48/50)
- 进入死信队列: 2 个

### 场景 3: Worker 崩溃模拟
- 崩溃任务数: 12
- 恢复执行任务数: 12
- 重复执行任务数: 0（幂等拦截生效）
- 重复写入结果数: 0

### 场景 4: 重复消息投递
- 投递消息数: 200
- 拦截消息数: 100
- 实际执行任务数: 100
- 重复结果数: 0
```

## 可调参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--scenario` | concurrent | 场景名（concurrent / bad_json / worker_crash / duplicate / timeout / judge_fail / all） |
| `--concurrency` | 50 | 并发任务数 |
| `--bad-json-rate` | 0.7 | 场景2中坏JSON注入比例 |
| `--timeout-rate` | 0.3 | 场景5中超时注入比例 |
| `--crash-at` | 50 | 场景3中第N个任务时崩溃 |
| `--replication` | 2 | 场景4中重复投递次数 |
| `--judge-pass-rate` | 0.0 | 场景6中评估通过率 |
| `--seed` | 42 | 随机种子，保证可复现 |
| `--reports-dir` | reports | 报告输出目录 |

## 实现要点

1. **接口对等**：`mock_infra.py` monkey-patch 了 `app.services.idempotency` / `app.services.queue` / `app.services.retry` / `app.services.orchestrator`，让真实业务代码不用改一行。
2. **故障注入开关**：`FailureInjector` 用全局概率开关，让 6 个场景共享同一套 mock 设施。
3. **指标聚合**：`MetricsCollector` 记录每个 task + 每个 step 的执行情况，结束时聚合成功率 / 延迟分位 / 重试分布。
4. **报告生成**：`report_generator.py` 把指标数据生成 Markdown + JSON + CSV，Markdown 末尾自动组织好简历片段。