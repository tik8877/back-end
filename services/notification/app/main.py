import asyncio
from contextlib import asynccontextmanager, suppress

import httpx
import structlog
from fastapi import FastAPI
from prometheus_client import make_asgi_app

from common.db import wait_for_database
from common.errors import install_error_handlers
from common.events import connect_broker
from common.observability import ObservabilityMiddleware, instrument_app, setup_logging, setup_metrics, setup_tracing
from services.notification.app.api import router
from services.notification.app.config import get_settings
from services.notification.app.consumer import consume_notifications
from services.notification.app.db import engine, session_factory
from services.notification.app.sender import TelegramSender


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
    client = httpx.AsyncClient()
    sender = TelegramSender(client, settings.telegram_stub_url, settings.telegram_timeout_seconds)
    task = asyncio.create_task(
        consume_notifications(broker, session_factory, sender, settings)
    )
    app.state.ready = True
    yield
    app.state.ready = False
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    await client.aclose()
    await broker.close()
    await engine.dispose()


app = FastAPI(title="FPM Notification API", version="1.0.0", lifespan=lifespan)
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
