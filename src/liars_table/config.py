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
