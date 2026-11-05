from functools import lru_cache

from pydantic_settings import SettingsConfigDict

from common.config import CommonSettings


class Settings(CommonSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "notification"
    telegram_stub_url: str = "http://telegram-stub:8000"
    telegram_timeout_seconds: float = 2.0
    max_delivery_attempts: int = 5
    delivery_delay_base_seconds: int = 2
    delivery_delay_max_seconds: int = 300
    queue_name: str = "notification.events"
    dead_queue_name: str = "notification.manual_review"
    prefetch_count: int = 50


@lru_cache
def get_settings() -> Settings:
    return Settings()
