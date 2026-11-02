from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, loaded from the environment or a local ``.env`` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    # 思考模式默认关闭：思维链会吃掉 max_tokens 导致 JSON 截断，
    # 而且开启后 temperature 不生效，所有 agent 说话会高度雷同。
    deepseek_thinking: bool = False
    deepseek_max_tokens: int = 800

    # Agent 决策预算。环境变量提供默认值，CLI/API 可以按本次对局覆盖。
    decision_timeout_seconds: float = 5.0
    decision_max_steps: int = 8
    decision_max_model_calls: int = 2
    decision_max_completion_tokens: int = 800
    decision_max_retries: int = 1

    # Embeddings
    embedding_provider: str = "dashscope"
    dashscope_api_key: str = ""
    embedding_model: str = "text-embedding-v3"

    # Runtime
    log_level: str = "INFO"
    database_url: str = "sqlite+pysqlite:///./data/liars.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
