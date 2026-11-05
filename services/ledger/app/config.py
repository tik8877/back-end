from functools import lru_cache

from pydantic_settings import SettingsConfigDict

from common.config import CommonSettings


class Settings(CommonSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "ledger"
    queue_name: str = "ledger.transfers"
    prefetch_count: int = 100
    statement_default_limit: int = 50
    statement_max_limit: int = 500


@lru_cache
def get_settings() -> Settings:
    return Settings()
