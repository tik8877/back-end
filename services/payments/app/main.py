import asyncio
from contextlib import asynccontextmanager, suppress

import httpx
import structlog
from fastapi import FastAPI
from prometheus_client import make_asgi_app

from common.db import wait_for_database
from common.errors import install_error_handlers
from common.events import connect_broker, publisher_worker
from common.observability import ObservabilityMiddleware, instrument_app, setup_logging, setup_metrics, setup_tracing
from services.payments.app.api import router
from services.payments.app.clients import AccountsClient, AntifraudClient
from services.payments.app.config import get_settings
from services.payments.app.db import engine, session_factory
from services.payments.app.recovery_worker import recovery_worker
from services.payments.app.service import TransferCoordinator


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.service_name, settings.log_level)
    setup_tracing(settings.service_name, settings.jaeger_endpoint, settings.environment, settings.service_version)
    try:
        setup_metrics(settings.prometheus_port)
    except OSError:
        structlog.get_logger().warning("metrics_port_busy", details={"port": settings.prometheus_port})
    await wait_for_database(engine, settings)
    client = httpx.AsyncClient()
    coordinator = TransferCoordinator(
        session_factory,
        AntifraudClient(client, settings.antifraud_service_url, settings.antifraud_timeout_seconds),
        AccountsClient(
            client,
            settings.accounts_service_url,
            settings.accounts_timeout_seconds,
            settings.accounts_status_check_attempts,
            settings.accounts_status_check_pause_seconds,
        ),
        settings,
    )
    app.state.coordinator = coordinator
    broker = await connect_broker(
        settings.rabbitmq_url,
        settings.dependency_connect_attempts,
        settings.dependency_retry_initial_seconds,
        settings.dependency_retry_max_seconds,
    )
    channel = await broker.channel(publisher_confirms=True, on_return_raises=True)
    tasks = [
        asyncio.create_task(recovery_worker(session_factory, coordinator, settings.recovery_interval_seconds, settings.max_processing_time_seconds, settings.recovery_batch_size)),
        asyncio.create_task(publisher_worker(session_factory, channel, settings.event_publish_interval_seconds, settings.event_publish_batch_size)),
    ]
    app.state.ready = True
    yield
    app.state.ready = False
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task
    await client.aclose()
    await broker.close()
    await engine.dispose()


app = FastAPI(title="FPM Payments API", version="1.0.0", lifespan=lifespan)
app.state.ready = False
app.add_middleware(ObservabilityMiddleware)
install_error_handlers(app)
app.include_router(router)
app.mount("/metrics", make_asgi_app())
instrument_app(app)


@app.get("/health/live")
async def live():
    return {"status": "ok"}


@app.get("/health/ready")
async def ready():
    if not app.state.ready:
        from common.errors import ServiceUnavailableError

        raise ServiceUnavailableError("Сервис ещё не готов")
    return {"status": "ready"}
