from functools import lru_cache

from pydantic_settings import SettingsConfigDict

from common.config import CommonSettings


class Settings(CommonSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "payments"
    accounts_service_url: str = "http://accounts:8000"
    antifraud_service_url: str = "http://antifraud:8000"
    antifraud_timeout_seconds: float = 0.2
    accounts_timeout_seconds: float = 2.0
    accounts_status_check_attempts: int = 2
    accounts_status_check_pause_seconds: float = 0.01
    safe_limit: int = 10_000
    recovery_interval_seconds: float = 5.0
    max_processing_time_seconds: int = 30
    recovery_batch_size: int = 100
    event_publish_interval_seconds: float = 1.0
    event_publish_batch_size: int = 100


@lru_cache
def get_settings() -> Settings:
    return Settings()
