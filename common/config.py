from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class CommonSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "service"
    environment: str = "dev"
    service_version: str = "1.0.0"
    log_level: str = "INFO"
    http_port: int = 8000
    prometheus_port: int = 9090
    jaeger_endpoint: str = "http://jaeger:4317"
    otel_exporter_otlp_endpoint: str = "http://jaeger:4317"
    database_url: str = "postgresql+asyncpg://fpm@postgres:5432/fpm"
    rabbitmq_url: str = "amqp://fpm@rabbitmq:5672/"
    redis_url: str = "redis://redis:6379/0"
    database_pool_size: int = 10
    database_pool_recycle_seconds: int = 1800
    shutdown_grace_seconds: float = 10.0
    dependency_connect_attempts: int = 8
    dependency_retry_initial_seconds: float = 0.25
    dependency_retry_max_seconds: float = 10.0


@lru_cache
def common_settings() -> CommonSettings:
    return CommonSettings()
