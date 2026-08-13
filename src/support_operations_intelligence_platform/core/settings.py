from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./support_ops_demo.sqlite3"
    action_timeout_seconds: float = 0.2
    action_max_attempts: int = 3

    model_config = SettingsConfigDict(env_prefix="SUPPORT_OPS_")


@lru_cache
def get_settings() -> Settings:
    return Settings()

