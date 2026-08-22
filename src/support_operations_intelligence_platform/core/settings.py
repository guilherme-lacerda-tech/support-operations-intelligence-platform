from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./support_ops_demo.sqlite3"
    sqlite_mode: str = "standard"
    action_timeout_seconds: float = 0.2
    action_max_attempts: int = 3
    action_retry_delay_seconds: float = 0.0
    action_lease_seconds: int = 60
    max_queue_backlog: int = 10_000

    model_config = SettingsConfigDict(env_prefix="SUPPORT_OPS_")


@lru_cache
def get_settings() -> Settings:
    return Settings()
