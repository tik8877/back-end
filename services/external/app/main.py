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
from services.external.app.api import router
from services.external.app.config import get_settings
from services.external.app.db import engine, session_factory
from services.external.app.everypay_client import EveryPayClient
from services.external.app.sync_worker import sync_worker


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
    client = httpx.AsyncClient()
    source = EveryPayClient(client, settings)
    tasks = [
        asyncio.create_task(sync_worker(session_factory, source, settings)),
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


app = FastAPI(title="FPM External API", version="1.0.0", lifespan=lifespan)
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
    return {"status": "ready" if app.state.ready else "starting"}
