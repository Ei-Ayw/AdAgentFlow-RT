"""全局配置 - 基于 pydantic-settings ，从 .env 读取"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """所有配置字段集中在这里，跨服务共享"""

    # ===== LLM =====
    anthropic_auth_token: str = ""
    anthropic_base_url: str = "https://api.minimaxi.com/anthropic"
    anthropic_default_haiku_model: str = "MiniMax-M3"
    anthropic_default_sonnet_model: str = "MiniMax-M3"
    llm_timeout: int = 30
    llm_max_retries: int = 3
    use_mock_llm: bool = False  # 没配模型时自动 mock

    # ===== Database =====
    database_url: str = "postgresql://adagent:change_me@localhost:5432/adagentflow"
    db_pool_size: int = 20
    db_max_overflow: int = 40
    db_pool_timeout: int = 10
    db_connect_timeout: int = 5
    db_statement_timeout_ms: int = 30000
    database_auto_create: bool = True  # 本地演示；生产应关闭并运行 Alembic

    # ===== Redis =====
    redis_url: str = "redis://localhost:6379/0"
    redis_idempotent_ttl: int = 86400  # 已完成标记保留时间
    redis_execution_lock_ttl: int = 300  # 执行锁租约，防止 Worker 崩溃后长期阻塞

    # ===== RabbitMQ =====
    rabbitmq_url: str = "amqp://adagent:change_me@localhost:5672/adagentflow"
    rabbitmq_prefetch: int = 8

    # ===== 任务配置 =====
    max_retry_count: int = 3
    retry_delays: str = "0,5,15"
    dead_letter_threshold: int = 3

    # ===== Transactional Outbox =====
    outbox_poll_interval: float = 1.0
    outbox_batch_size: int = 100
    outbox_max_attempts: int = 20
    outbox_lock_timeout: int = 60

    # ===== Langfuse (可观测) =====
    langfuse_enabled: bool = False
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    # ===== 日志 =====
    log_level: str = "INFO"
    log_format: str = "json"
    service_name: str = "adagentflow"

    # ===== Worker =====
    worker_shutdown_timeout: int = 30

    # ===== API =====
    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000"

    @property
    def cors_origin_list(self) -> List[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

    # ===== 派生属性 =====
    @property
    def retry_delay_list(self) -> List[int]:
        return [int(x) for x in self.retry_delays.split(",") if x.strip()]

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
