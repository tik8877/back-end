from functools import lru_cache

from pydantic_settings import SettingsConfigDict

from common.config import CommonSettings


class Settings(CommonSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "antifraud"
    decision_ttl_seconds: int = 15_552_000
    history_window_seconds: int = 60
    decision_lock_ttl_seconds: int = 2
    decision_lock_wait_attempts: int = 10
    decision_lock_wait_seconds: float = 0.002
    default_frequency_limit: int = 20
    default_amount_limit: int = 1_000_000
    storage_failure_allow: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
