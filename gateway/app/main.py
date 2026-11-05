import asyncio
from contextlib import asynccontextmanager, suppress

import httpx
import structlog
import uvicorn
from fastapi import FastAPI
from prometheus_client import make_asgi_app
from redis.asyncio import Redis

from common.observability import ObservabilityMiddleware, instrument_app, setup_logging, setup_metrics, setup_tracing
from gateway.app.api import (
    routes_accounts,
    routes_auth,
    routes_cashback,
    routes_external,
    routes_ledger,
    routes_misc,
    routes_payments,
)
from gateway.app.config import get_settings
from gateway.app.core.availability_guard import ServiceAvailabilityGuard
from gateway.app.core.errors import install_error_handlers
from gateway.app.core.middleware import AccessLogMiddleware, RequestIdMiddleware


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.service_name, settings.log_level)
    setup_tracing(
        settings.service_name,
        settings.jaeger_endpoint,
        settings.environment,
        settings.service_version,
    )
    try:
        setup_metrics(settings.prometheus_port)
    except OSError:
        structlog.get_logger().warning("metrics_port_busy", details={"port": settings.prometheus_port})
    timeout = httpx.Timeout(
        settings.upstream_timeout_seconds,
        connect=settings.upstream_connect_timeout_seconds,
    )
    app.state.http_client = httpx.AsyncClient(
        timeout=timeout,
        limits=httpx.Limits(
            max_connections=settings.http_max_connections,
            max_keepalive_connections=settings.http_keepalive_connections,
        ),
    )
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    app.state.availability_guard = ServiceAvailabilityGuard(
        app.state.redis, settings, app.state.http_client
    )
    probe_task = asyncio.create_task(app.state.availability_guard.probe_worker())
    yield
    probe_task.cancel()
    with suppress(asyncio.CancelledError):
        await probe_task
    await app.state.http_client.aclose()
    await app.state.redis.aclose()


app = FastAPI(title="FPM Gateway API", version="1.0.0", lifespan=lifespan)
app.add_middleware(ObservabilityMiddleware)
app.add_middleware(AccessLogMiddleware)
app.add_middleware(RequestIdMiddleware)
install_error_handlers(app)
app.include_router(routes_auth.router)
app.include_router(routes_accounts.router)
app.include_router(routes_payments.router)
app.include_router(routes_ledger.router)
app.include_router(routes_cashback.router)
app.include_router(routes_external.router)
app.include_router(routes_misc.router)
app.mount("/metrics", make_asgi_app())
instrument_app(app)


@app.get("/health/live", tags=["health"])
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def ready() -> dict[str, str]:
    try:
        await app.state.redis.ping()
        response = await app.state.http_client.get(f"{settings.auth_service_url}/health/live")
        response.raise_for_status()
    except (httpx.HTTPError, RuntimeError, ConnectionError):
        from gateway.app.core.errors import ServiceUnavailableError

        raise ServiceUnavailableError("Шлюз ещё не готов")
    return {"status": "ready"}


if __name__ == "__main__":
    uvicorn.run("gateway.app.main:app", host="0.0.0.0", port=settings.http_port)
