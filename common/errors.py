from dataclasses import dataclass
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from common.observability import current_trace_id


@dataclass(slots=True)
class AppError(Exception):
    error_code: str
    message: str
    http_status: int = 400
    details: dict[str, Any] | None = None
    headers: dict[str, str] | None = None


class BadRequestError(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, 400)


class UnauthorizedError(AppError):
    def __init__(self, code: str = "UNAUTHORIZED", message: str = "Требуется авторизация") -> None:
        super().__init__(code, message, 401)


class ForbiddenError(AppError):
    def __init__(self, code: str = "FORBIDDEN", message: str = "Доступ запрещён") -> None:
        super().__init__(code, message, 403)


class NotFoundError(AppError):
    def __init__(self, code: str = "NOT_FOUND", message: str = "Объект не найден") -> None:
        super().__init__(code, message, 404)


class ConflictError(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, 409)


class RateLimitError(AppError):
    def __init__(self, retry_after: int) -> None:
        super().__init__(
            "RATE_LIMITED",
            "Слишком много запросов",
            429,
            headers={"Retry-After": str(retry_after)},
        )


class ServiceUnavailableError(AppError):
    def __init__(self, message: str = "Сервис временно недоступен") -> None:
        super().__init__("SERVICE_UNAVAILABLE", message, 503)


class UpstreamError(AppError):
    def __init__(self, message: str = "Ошибка зависимого сервиса") -> None:
        super().__init__("UPSTREAM_ERROR", message, 502)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "error_code": exc.error_code,
                "message": exc.message,
                "trace_id": current_trace_id(),
            },
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def handle_unknown_error(_: Request, exc: Exception) -> JSONResponse:
        structlog.get_logger().exception(
            "unhandled_error",
            details={"error_type": type(exc).__name__},
        )
        return JSONResponse(
            status_code=500,
            content={
                "error_code": "INTERNAL_ERROR",
                "message": "Внутренняя ошибка",
                "trace_id": current_trace_id(),
            },
        )
