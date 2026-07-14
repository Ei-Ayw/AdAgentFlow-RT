# 凭证轮换与 Git 历史清理

## 已确认状态

- 当前 `.env` 已被 Git 忽略且不再处于 HEAD；
- Git 历史中仍存在 `.env` 记录，因此旧 Token/密码必须视为已经泄露；
- 应先轮换凭证，再清理历史。只重写历史不能使已经复制的 Token 失效。

## 轮换顺序

1. 在模型供应商控制台创建新 Token，先以 Secret 注入测试环境；
2. 验证一次真实 LLM smoke test；
3. 更新生产 Secret/CI Secret，滚动重启 API 与 Worker；
4. 撤销旧 Token，并检查供应商审计日志和异常消费；
5. 轮换 PostgreSQL、RabbitMQ、Langfuse、NextAuth 等历史密码；
6. 不要把新值写入 Issue、聊天、命令行参数或 Git 文件。

## 历史清理

以下操作会改写所有分支和标签，必须先通知协作者并创建远端备份。建议在干净的临时 clone 中执行：

```bash
git filter-repo --path .env --invert-paths --force
git log --all -- .env
```

确认第二条命令无输出后，再由仓库管理员执行受保护分支允许的 force push：

```bash
git push --force --all origin
git push --force --tags origin
```

所有协作者应重新 clone；旧 clone、Fork、CI artifact 和缓存仍可能保留旧值，需要单独删除。不要在当前有未提交改动的工作区执行历史重写。

## 持续防护

- 在 CI 和本地 pre-commit 中启用 Gitleaks；
- GitHub/GitLab 开启 Secret Scanning 和 push protection；
- 生产只通过 Secret Manager/Kubernetes Secret 注入；
- 日志只记录供应商、模型和请求 ID，不记录 Authorization 请求头或完整 Token。
