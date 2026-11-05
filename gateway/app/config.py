from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from common.config import CommonSettings


class Settings(CommonSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "gateway"
    jwt_public_key: str = ""
    jwt_public_keys: dict[str, str] = Field(default_factory=dict)
    jwt_public_key_path: Path | None = None
    jwt_algorithm: str = "RS256"
    jwt_audience: str = "fpm-api"
    jwt_issuer: str = "fpm-auth"
    rate_limit_per_user_per_minute: int = 120
    rate_limit_window_seconds: int = 60
    upstream_timeout_seconds: float = 3.0
    upstream_connect_timeout_seconds: float = 1.0
    service_unavailable_threshold: int = 5
    service_unavailable_cooldown_seconds: int = 30
    service_unavailable_probe_interval_seconds: int = 10
    auth_service_url: str = "http://auth:8000"
    accounts_service_url: str = "http://accounts:8000"
    payments_service_url: str = "http://payments:8000"
    ledger_service_url: str = "http://ledger:8000"
    antifraud_service_url: str = "http://antifraud:8000"
    notification_service_url: str = "http://notification:8000"
    cashback_service_url: str = "http://cashback:8000"
    external_service_url: str = "http://external:8000"
    max_request_body_bytes: int = Field(default=1_048_576, ge=1024)
    http_max_connections: int = 200
    http_keepalive_connections: int = 50

    @property
    def service_urls(self) -> dict[str, str]:
        return {
            "auth": self.auth_service_url,
            "accounts": self.accounts_service_url,
            "payments": self.payments_service_url,
            "ledger": self.ledger_service_url,
            "antifraud": self.antifraud_service_url,
            "notification": self.notification_service_url,
            "cashback": self.cashback_service_url,
            "external": self.external_service_url,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
