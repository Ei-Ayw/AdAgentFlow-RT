# Database migrations

生产和共享环境使用 Alembic 升级数据库：

```bash
alembic upgrade head
```

新增或修改 ORM 模型后生成迁移并人工检查：

```bash
alembic revision --autogenerate -m "describe_change"
```

`Base.metadata.create_all()` 仅保留给本地演示和测试；生产部署应先运行迁移。
