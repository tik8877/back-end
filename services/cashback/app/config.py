from functools import lru_cache

from pydantic_settings import SettingsConfigDict

from common.config import CommonSettings


class Settings(CommonSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "cashback"
    queue_name: str = "cashback.transactions"
    prefetch_count: int = 100
    cashback_period_seconds: int = 2_592_000
    accrual_scan_interval_seconds: float = 60.0
    accrual_batch_size: int = 500


@lru_cache
def get_settings() -> Settings:
    return Settings()
