"""Environment-only configuration (Pydantic Settings)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    sqlite_path: str = "./data/do_short.db"
    base_url: str = "http://localhost:8000"
    rate_limit_requests: int = 30
    rate_limit_window_seconds: int = 60
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
