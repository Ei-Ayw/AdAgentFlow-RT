# AdAgentFlow 业务客户端前端设计

**日期**：2026-07-14
**目标用户**：电商商家 / 品牌主（提交商品、查看广告生成结果、不满意可重生）
**作用范围**：新增面向业务用户的 Web 客户端 SPA，与现有 `app/dashboard/`（运维 Dashboard）并存，不替换

---

## 1. 背景与目标

AdAgentFlow 后端已具备完整的 5 节点 Agent 链 + 评估闭环 + 死信接管能力，并通过 `app/dashboard/` 提供**运维视角**的可观测页（任务总览、节点成功率、死信列表、Trace 甘特图）。

当前缺失的是**业务视角**的客户端：商家提交商品后看不到 5 步节点在跑什么、拿不到清晰结构化的脚本 / 分镜 / 素材结果、不满意时没有友好的重生入口。

本设计交付一个面向商家的 SPA：
- 让商家直观看到 5 步 Agent 实时进度
- 让商家清晰消费最终结构化结果（脚本 / 分镜 / 素材 / 质量评分）
- 提供「换个风格重生」与「反馈重生」两条循环路径
- 历史任务可回溯

## 2. 技术选型

| 维度 | 选型 | 理由 |
|------|------|------|
| 框架 | Vue 3（CDN 引入） | 免构建、与现有静态目录风格一致；组件化有助复用 |
| 路由 | hash 路由（自实现 30 行） | 不引入 vue-router，单页 4 个路由足够 |
| 样式 | Tailwind CSS（CDN） | 减少手写 CSS，与运维 Dashboard 视觉接近 |
| 实时进度 | 3s 轮询 | 后端无 WS、任务 8-15s 完成，3s 足够流畅 |
| 后端通信 | 现有 REST API 全部复用，零改动；仅「反馈重生」需小扩展 | 见 §6 |
| 部署 | 静态文件挂到 FastAPI 静态目录 `app/web/static/`，新增一条挂载 | 不引入新服务 |

## 3. 路由与页面

| 路由 | 页面 | 作用 |
|------|------|------|
| `#/` | TaskListPage | 任务列表（首页），有筛选 + 搜索 + 自动轮询 |
| `#/submit` | SubmitPage | 提交新任务表单 |
| `#/task/:id` | TaskDetailPage | 5 步进度 + 实时输出 + 最终结果 |
| `#/task/:id/trace` | redirect → `/dashboard/trace.html?task_id={id}` | 跳到运维 Trace 甘特图 |

**目录结构**
```
app/web/                      # 整个目录被 FastAPI 静态托管
├── index.html                # SPA 入口（路径 /web/index.html 或 /）
├── main.js                   # Vue 启动 + 路由
├── api.js                    # fetch 封装 + 轮询工具
├── style.css                 # Tailwind 引入 + 自定义变量
├── components/
│   ├── AgentStepper.vue      # 5 步节点状态机组件
│   ├── StepOutputCard.vue    # 单节点输出卡片（按 schema 切换布局）
│   ├── StatusBadge.vue       # 状态色标
│   └── TaskCard.vue          # 列表项
└── pages/
    ├── TaskListPage.vue
    ├── SubmitPage.vue
    └── TaskDetailPage.vue
```

## 4. 页面布局

### 4.1 任务列表 `#/`

- 顶部：标题 + 「+ 提交新任务」CTA
- 筛选条：状态枚举下拉 + 搜索框（按 task_id / product_name）
- 主体：TaskCard 列表，按 `created_at` 倒序
- 分页：上 / 下页 + 总数
- 空状态：插画 + 「还没有任务」+ 「立即创建」CTA

**TaskCard 字段**：product_name、platform、duration、status 徽章、retry_count、最近 step 摘要、创建时间

**轮询策略**：仅在存在非终态任务时启动 5s 轮询，否则仅做用户触发的拉取

### 4.2 提交新任务 `#/submit`

**两段式表单**：

- **Step 1 · 商品信息**
  - `product_name`（必填，文本）
  - `target_user`（选填，文本）
  - `selling_points`（必填 ≥1，动态列表 + 添加 / 删除按钮）
- **Step 2 · 投放参数**
  - `platform`（单选：TikTok / Instagram / YouTube Shorts）
  - `style`（6 个预设下拉，前 3 个来自 `docs/PROMPTS.md` 的 `STYLE_OPTIONS`）
  - `duration`（滑块 5-60，默认 15）

**底部**：预估 token / 耗时说明 + 取消 / 提交按钮

**提交行为**：
- 客户端做必填校验
- 提交按钮 loading 时禁用
- 成功 → `localStorage.setItem('recent_task_id', task_id)` + 跳转 `#/task/{task_id}`
- 失败 → 顶部 toast

### 4.3 任务详情 `#/task/:id`（核心页）

**头部**：
- 返回列表 + product_name + platform + duration
- 状态横幅（颜色按 `task.status` 区分）
- 进度条 + 「第 N/5 步」

**5 步 Agent 进度（AgentStepper）**：
- 5 行：商品理解 / 广告脚本 / 分镜规划 / 素材建议 / 质量评估
- 每行：序号 + 名称 + 状态图标 + 耗时 + 展开/折叠按钮
- 「当前节点输出」始终展开最近一个 `running` 节点
- `failed` 节点自动展开错误

**当前节点输出预览（StepOutputCard）**：根据 step_id 切换布局：
- `product_analysis` → 痛点 / 目标用户 / 卖点 / 切入角度
- `script_generation` → 钩子 / 痛点 / 方案 / 信任 / CTA / 完整脚本
- `storyboard_planning` → 5 镜时间轴（点击单镜展开画面 / 字幕 / 配音）
- `material_suggestion` → 素材列表（每镜对应的搜索关键词）
- `quality_evaluation` → 评分 + 风险等级 + 改进建议 + issues

**任务终态后，下半区变成「最终结果区」**：
- ⭐ 质量评分卡
- 📝 广告脚本完整卡（可复制 / 导出）
- 🎬 分镜表（5 镜时间轴 + 单镜展开）
- 🖼 素材建议（每镜对应）
- 操作栏：[换个风格重生] [反馈重生] [复制全部]

**不同终态的差异化行为**：

| task.status | 横幅 | 行为 |
|------------|------|------|
| `running` / `evaluating` / `retrying` / `queued` | 蓝色「生成中」+ 进度环 | 禁用所有重生按钮，显示当前 step |
| `success` | 绿色「生成成功」+ 质量分 | 展示全部结果，启用操作栏 |
| `manual_review` | 黄色「请人工审核」+ 风险说明 | 仍展示结果，顶部加提示 |
| `failed` | 红色「生成失败」+ 原因 | 折叠结果，启用「再次尝试」 |
| `dead_letter` | 深红「已多次失败」+ 建议 | 折叠结果，启用「再次尝试」+ 引导简化输入 |

## 5. 实时进度机制

### 5.1 轮询工具 `api.js`

```js
// 单一函数处理详情页轮询
export function pollTaskUntilDone(taskId, { intervalMs = 3000, timeoutMs = 300_000 } = {}) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs
    const tick = async () => {
      try {
        const task = await fetchTask(taskId)
        if (isTerminal(task.status)) {
          const timeline = await fetchTimeline(taskId).catch(() => null)
          return resolve({ task, timeline })
        }
        if (Date.now() > deadline) return reject(new Error('轮询超时'))
        setTimeout(tick, intervalMs)
      } catch (e) { reject(e) }
    }
    tick()
  })
}

const TERMINAL = new Set(['success', 'failed', 'dead_letter', 'manual_review'])
```

### 5.2 列表页轮询（不同策略）

- 仅在列表中存在非终态任务时启动
- 间隔 5s（比详情页长，省请求）
- 一旦所有任务都进入终态，立即停止

### 5.3 状态机映射（`AgentStepper` 内部）

| step.status | 视觉 | 行为 |
|-------------|------|------|
| `pending` | 灰色空圆 | 文字「等待中」 |
| `running` | 蓝色旋转图标 | 文字「运行中…」+ 自动展开输出 |
| `success` | 绿色 ✓ | 默认折叠输出，点击展开 |
| `failed` | 红色 ✗ | 自动展开错误信息 |
| `retrying` | 黄色 ⟳ | 文字「第 N 次重试中」+ 失败原因 |
| `skipped` | 灰色 — | 折叠 |

## 6. 后端 API 依赖与扩展

### 6.1 复用现有 API

| 用途 | 接口 | 文件 |
|------|------|------|
| 提交任务 | `POST /api/v1/tasks/submit` | `app/api/task_router.py:38` |
| 任务详情（含 steps） | `GET /api/v1/tasks/{task_id}` | `app/api/task_router.py:85` |
| 任务列表 | `GET /api/v1/tasks/?status=&limit=&offset=` | `app/api/task_router.py:127` |
| Trace 时间线 | `GET /api/v1/traces/by-task/{task_id}/timeline` | `app/api/trace_router.py:80` |

**前端读 step.output_payload 拿业务结果**（脚本 / 分镜 / 素材 / 评价均存在 `task_steps.output_payload` JSONB 字段）。

### 6.2 需要后端小扩展：「反馈重生」

**问题**：当前 `POST /tasks/submit` 接受商品输入，不支持「拿上一次的 task 结果做反馈重生」。

**扩展方案**：在 `SubmitTaskRequest`（`app/api/task_router.py:18`）新增可选字段：

```python
class SubmitTaskRequest(BaseModel):
    # ... 现有字段 ...
    feedback_for_task_id: Optional[str] = Field(
        None, description="若不为空，则把该 task 的输出作为反馈带入新任务"
    )
    style_override: Optional[str] = Field(
        None, description="重生时强制覆盖 style"
    )
```

在 `orchestrator.create_task`（`app/services/orchestrator.py:54`）中：
- 若 `feedback_for_task_id` 非空，从 DB 读取该 task 的 `EvaluationResult`（最新一条）
- 把 `failure_feedback` 字段按以下格式拼接后写入 queue payload：
  ```
  score={eval.score}
  issues={'\n'.join(i.detail for i in eval.issues)}
  suggested_fix={eval.suggested_fix}
  ```
- 起始节点改为 `script_generation`（跳过 `product_analysis`），并把上次 `product_analysis` 的输出塞进 `history` 字段
- 若请求带 `style_override`，覆盖 `product.style` 后再写入

**改动量**：约 30 行，含 1 个新测试。

## 7. 错误处理

| 错误源 | 表现 | UI 处理 |
|--------|------|---------|
| 表单 422 | 字段校验失败 | 字段下方红字，定位首个错误 |
| 后端 5xx | 提交 / 查询失败 | 顶部黄色 toast「服务异常」+ 重试按钮 |
| 网络断开 | fetch reject | 顶部红色「网络中断」横条，恢复自动重试 1 次 |
| 任务 404 | 详情页找不到 | 全屏「任务不存在」+ 「返回列表」 |
| 轮询超时 (>5min) | 任务卡住罕见 | 黄色提示「任务长时间未完成」+ 「取消轮询」按钮 |

**边界场景**：
- 列表为空：插画 + 「还没有任务」CTA
- 结果 JSON 字段缺失（schema 漂移）：单字段 `—`，卡片不崩
- 分镜 0 镜：占位「分镜生成失败，可反馈重生」
- 评价 issues 为空：不显示 issues 区块
- trace 数据为空：占位 + 「重试拉取」

## 8. 数据流时序

```
用户                       SPA                            FastAPI
 │   1. 填表单点提交            │                                 │
 ├────────────────────────────►│ POST /tasks/submit              │
 │                              ├────────────────────────────────►│
 │                              │ 201 {task_id, trace_id}         │
 │                              │◄────────────────────────────────┤
 │   2. 跳转 #/task/{id}        │                                 │
 │◄─────────────────────────────┤                                 │
 │                              │ poll loop start                 │
 │                              │ GET /tasks/{id}  (3s)           │
 │                              ├────────────────────────────────►│
 │                              │ {status, steps, retry_count}    │
 │                              │◄────────────────────────────────┤
 │   3. step 1 完成             │  ... 继续轮询 ...                │
 │◄─────────────────────────────┤  终态时:                        │
 │                              │ GET /traces/by-task/{id}/timeline│
 │                              ├────────────────────────────────►│
 │                              │ {task, steps, traces, evals}    │
 │                              │◄────────────────────────────────┤
 │   4. 看到完整结果            │ poll loop end                   │
 │◄─────────────────────────────┤                                 │
```

## 9. 测试策略

**3 层测试 + 3 个最低必跑测试**

| 层 | 工具 | 覆盖 |
|----|------|------|
| 单元 | Vitest | `pollTaskUntilDone`、`StatusBadge` 颜色映射、`AgentStepper` 状态映射 |
| 组件 | Vitest + @vue/test-utils | 详情页在 mock 数据下渲染 success / running / dead_letter |
| 端到端 | Playwright（可选，暂缓） | 提交 → 看到结果（mock LLM 模式） |

**3 个最低必跑测试**：

1. `pollTaskUntilDone` 正确在终态时停止（用 `vi.useFakeTimers`）
2. `AgentStepper` 在 running → success 状态切换时正确显示
3. 详情页在 `success` 状态时正确渲染 4 张结果卡（脚本 / 分镜 / 素材 / 评分）

## 10. 部署

- 新增 `app/web/` 目录，与 `app/dashboard/` 平级
- `app/main.py` 增加一行 `app.mount("/web", StaticFiles(directory="app/web", html=True), name="web")`（与 `app/dashboard` 同样的挂载方式）
- 入口 `app/web/index.html` 访问路径为 `/web/`
- 不引入新服务、不改 docker-compose

## 11. 风险与权衡

| 风险 | 应对 |
|------|------|
| 轮询导致后端 QPS 上升 | 仅在有非终态任务时轮询；3s 间隔；用户关闭页面即停 |
| 商家对「Agent 在跑什么」无感 | 进度条 + 当前节点输出预览双重反馈 |
| 「反馈重生」依赖后端扩展 | spec §6.2 已说明；如拒绝扩展，可降级为「重提交并人工把上次结果粘贴到 feedback_for_task_id 旁路」 |
| 任务结果数据大（5 步 output_payload 累计可达 50KB） | 单页加载可承受；不分页不分次拉取 |
| 与运维 Dashboard 风格不一致 | 复用 Tailwind + 现有 CSS 变量；颜色系统保持接近 |

## 12. 验收标准

- [ ] 商家能在 30s 内完成提单（填写 + 点击）
- [ ] 提单后 1s 内看到第 1 步节点变为 running
- [ ] 任务进行中能清楚看到 5 步中哪一步在跑、当前输出是什么
- [ ] 任务完成后能看到 4 张结果卡（脚本 / 分镜 / 素材 / 评分）
- [ ] 「换个风格重生」能在 1 次点击内发起新任务
- [ ] 「反馈重生」（如后端扩展完成）能带入上次的 issues / suggested_fix
- [ ] 历史任务列表按时间倒序展示、可按状态筛选
- [ ] 所有错误状态有友好提示，不出现白屏
- [ ] 3 个最低测试通过
