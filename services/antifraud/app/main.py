from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from prometheus_client import make_asgi_app
from redis.asyncio import Redis

from common.errors import install_error_handlers
from common.observability import ObservabilityMiddleware, instrument_app, setup_logging, setup_metrics, setup_tracing
from services.antifraud.app.api import router
from services.antifraud.app.config import get_settings
from services.antifraud.app.rules import DecisionService
from services.antifraud.app.storage import DecisionStorage


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.service_name, settings.log_level)
    setup_tracing(settings.service_name, settings.jaeger_endpoint, settings.environment, settings.service_version)
    try:
        setup_metrics(settings.prometheus_port)
    except OSError:
        structlog.get_logger().warning("metrics_port_busy", details={"port": settings.prometheus_port})
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    app.state.redis = redis
    app.state.decision_service = DecisionService(DecisionStorage(redis, settings), settings)
    app.state.ready = await redis.ping()
    yield
    app.state.ready = False
    await redis.aclose()


app = FastAPI(title="FPM Antifraud API", version="1.0.0", lifespan=lifespan)
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
