"""全局配置 - 基于 pydantic-settings ，从 .env 读取"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """所有配置字段集中在这里，跨服务共享"""

    # ===== LLM (minimax responses 协议) =====
    anthropic_auth_token: str = ""  # 历史字段名复用，实际为 minimax API key
    anthropic_base_url: str = "https://api.minimaxi.com"  # minimax base，路径会补 /v1/responses
    anthropic_default_haiku_model: str = "MiniMax-M3"
    anthropic_default_sonnet_model: str = "MiniMax-M3"
    llm_timeout: int = 30
    llm_max_retries: int = 3
    use_mock_llm: bool = True  # 没配模型时自动 mock

    # ===== Database =====
    database_url: str = "postgresql://adagent:adagent_secret_2026@localhost:5432/adagentflow"
    db_pool_size: int = 20
    db_max_overflow: int = 40

    # ===== Redis =====
    redis_url: str = "redis://localhost:6379/0"
    redis_idempotent_ttl: int = 86400  # 24 小时

    # ===== RabbitMQ =====
    rabbitmq_url: str = "amqp://adagent:adagent_secret_2026@localhost:5672/adagentflow"
    rabbitmq_prefetch: int = 8

    # ===== 任务配置 =====
    max_retry_count: int = 3
    retry_delays: str = "0,5,15"
    dead_letter_threshold: int = 3

    # ===== Langfuse (可观测) =====
    langfuse_enabled: bool = False
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    # ===== 日志 =====
    log_level: str = "INFO"

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
