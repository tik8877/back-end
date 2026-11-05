import asyncio
from contextlib import asynccontextmanager, suppress

import structlog
from fastapi import FastAPI
from prometheus_client import make_asgi_app

from common.db import wait_for_database
from common.events import connect_broker, publisher_worker
from common.observability import ObservabilityMiddleware, instrument_app, setup_logging, setup_metrics, setup_tracing
from common.errors import install_error_handlers
from services.accounts.app.api import router
from services.accounts.app.closing_worker import closing_worker
from services.accounts.app.config import get_settings
from services.accounts.app.db import engine, session_factory
from services.accounts.app.reservations_worker import reservations_worker


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
    broker = await connect_broker(
        settings.rabbitmq_url,
        settings.dependency_connect_attempts,
        settings.dependency_retry_initial_seconds,
        settings.dependency_retry_max_seconds,
    )
    channel = await broker.channel(publisher_confirms=True, on_return_raises=True)
    tasks = [
        asyncio.create_task(reservations_worker(session_factory, settings.reservation_scan_interval_seconds, settings.worker_batch_size)),
        asyncio.create_task(closing_worker(session_factory, settings.closing_scan_interval_seconds, settings.close_account_min_idle_days, settings.worker_batch_size)),
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
    await broker.close()
    await engine.dispose()


app = FastAPI(title="FPM Accounts API", version="1.0.0", lifespan=lifespan)
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
