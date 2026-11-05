from functools import lru_cache

from pydantic_settings import SettingsConfigDict

from common.config import CommonSettings


class Settings(CommonSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "external"
    everypay_base_url: str = "http://everypay-stub:8000"
    everypay_api_key: str = ""
    external_timeout_seconds: float = 3.0
    external_wait_base_seconds: float = 0.2
    external_wait_max_seconds: float = 30.0
    external_max_attempts: int = 8
    sync_scan_interval_seconds: float = 1.0
    sync_batch_size: int = 50
    event_publish_interval_seconds: float = 1.0
    event_publish_batch_size: int = 100


@lru_cache
def get_settings() -> Settings:
    return Settings()
