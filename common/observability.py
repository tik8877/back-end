import contextvars
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from fastapi import FastAPI, Request, Response
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.aio_pika import AioPikaInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import DEPLOYMENT_ENVIRONMENT, SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Histogram, start_http_server
from starlette.middleware.base import BaseHTTPMiddleware


USER_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("user_id", default=None)
SERVICE_CONTEXT: contextvars.ContextVar[str] = contextvars.ContextVar("service", default="service")
SENSITIVE_KEY = re.compile(r"password|token|secret|authorization", re.IGNORECASE)

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Количество HTTP-запросов",
    ("service", "method", "path", "status"),
)
HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "Длительность HTTP-запросов",
    ("service", "method", "path"),
)
DEPENDENCY_ERRORS = Counter(
    "service_dependency_errors_total",
    "Ошибки зависимых сервисов",
    ("service", "dependency"),
)
BUSINESS_OPERATIONS = Counter(
    "business_operations_total",
    "Результаты бизнес-операций",
    ("service", "operation", "status"),
)


def _mask(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "***" if SENSITIVE_KEY.search(str(key)) else _mask(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask(item) for item in value]
    return value


def _add_context(_: Any, __: str, event: dict[str, Any]) -> dict[str, Any]:
    span_context = trace.get_current_span().get_span_context()
    event["service"] = SERVICE_CONTEXT.get()
    event["trace_id"] = f"{span_context.trace_id:032x}" if span_context.is_valid else None
    event["span_id"] = f"{span_context.span_id:016x}" if span_context.is_valid else None
    event["user_id"] = USER_ID.get()
    event.setdefault("details", {})
    return _mask(event)


def setup_logging(service_name: str, level: str = "INFO") -> None:
    SERVICE_CONTEXT.set(service_name)
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
            _add_context,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def setup_tracing(service_name: str, endpoint: str, environment: str, version: str) -> None:
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        return
    provider = TracerProvider(
        resource=Resource.create(
            {
                SERVICE_NAME: service_name,
                SERVICE_VERSION: version,
                DEPLOYMENT_ENVIRONMENT: environment,
            }
        )
    )
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)))
    trace.set_tracer_provider(provider)
    HTTPXClientInstrumentor().instrument()
    SQLAlchemyInstrumentor().instrument()
    AioPikaInstrumentor().instrument()


def setup_metrics(port: int) -> None:
    start_http_server(port)


def instrument_app(app: FastAPI) -> None:
    FastAPIInstrumentor.instrument_app(app)


def current_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return f"{context.trace_id:032x}" if context.is_valid else None


def bind_user_context(user_id: str | None) -> contextvars.Token[str | None]:
    return USER_ID.set(user_id)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        started = time.perf_counter()
        user_id = request.headers.get("X-User-Id")
        token = bind_user_context(user_id)
        status = 500
        route_path = request.url.path
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Trace-Id"] = current_trace_id() or request.headers.get("X-Trace-Id", "")
            return response
        finally:
            service = SERVICE_CONTEXT.get()
            HTTP_REQUESTS.labels(service, request.method, route_path, str(status)).inc()
            HTTP_DURATION.labels(service, request.method, route_path).observe(time.perf_counter() - started)
            USER_ID.reset(token)
