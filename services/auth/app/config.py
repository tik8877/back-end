from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from common.config import CommonSettings


class Settings(CommonSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "auth"
    jwt_private_key: str = ""
    jwt_private_key_path: Path | None = None
    jwt_public_key: str = ""
    jwt_public_key_path: Path | None = None
    jwt_public_keys: dict[str, str] = Field(default_factory=dict)
    jwt_algorithm: str = "RS256"
    jwt_audience: str = "fpm-api"
    jwt_issuer: str = "fpm-auth"
    jwt_active_kid: str = "local-dev"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 2_592_000
    bcrypt_rounds: int = 12
    login_window_seconds: int = 60
    login_attempts_per_ip: int = 30
    login_attempts_per_login: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()
