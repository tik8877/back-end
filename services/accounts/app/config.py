from functools import lru_cache

from pydantic_settings import SettingsConfigDict

from common.config import CommonSettings


class Settings(CommonSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "accounts"
    reservation_ttl_seconds: int = 900
    reservation_scan_interval_seconds: float = 5.0
    closing_scan_interval_seconds: float = 300.0
    close_account_min_idle_days: int = 30
    event_publish_interval_seconds: float = 1.0
    event_publish_batch_size: int = 100
    worker_batch_size: int = 100


@lru_cache
def get_settings() -> Settings:
    return Settings()
