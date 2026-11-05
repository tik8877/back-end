import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
from fastapi import Request
from fastapi.responses import StreamingResponse

from common.observability import DEPENDENCY_ERRORS, current_trace_id
from gateway.app.config import Settings
from gateway.app.core.availability_guard import ServiceAvailabilityGuard
from gateway.app.core.errors import BadRequestError, ServiceUnavailableError, UpstreamError


RESPONSE_HEADER_ALLOWLIST = {
    "content-type",
    "content-length",
    "x-trace-id",
    "x-request-id",
    "retry-after",
    "location",
}


def filter_response_headers(headers: httpx.Headers) -> dict[str, str]:
    return {key: value for key, value in headers.items() if key.lower() in RESPONSE_HEADER_ALLOWLIST}


async def _response_body(response: httpx.Response) -> AsyncIterator[bytes]:
    try:
        async for chunk in response.aiter_bytes():
            yield chunk
    finally:
        await response.aclose()


async def proxy_request(
    request: Request,
    target_url: str,
    service_name: str,
    settings: Settings,
) -> StreamingResponse:
    guard: ServiceAvailabilityGuard = request.app.state.availability_guard
    if await guard.should_reject_fast(service_name):
        raise ServiceUnavailableError()

    body = await request.body()
    if len(body) > settings.max_request_body_bytes:
        raise BadRequestError("REQUEST_TOO_LARGE", "Тело запроса слишком велико")

    request_id = getattr(request.state, "request_id", None) or request.headers.get(
        "X-Request-Id", str(uuid4())
    )
    headers = {
        "X-User-Id": str(request.state.user_id),
        "X-User-Roles": ",".join(request.state.user_roles),
        "X-Trace-Id": current_trace_id() or request.headers.get("X-Trace-Id", ""),
        "X-Request-Id": request_id,
        "X-Client-Ip": request.client.host if request.client else "unknown",
    }
    for name in ("Content-Type", "Accept", "Idempotency-Key"):
        if value := request.headers.get(name):
            headers[name] = value

    client: httpx.AsyncClient = request.app.state.http_client
    outgoing = client.build_request(
        request.method,
        target_url,
        params=request.query_params,
        headers=headers,
        content=body,
    )
    try:
        response = await client.send(outgoing, stream=True)
    except asyncio.CancelledError:
        raise
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        await guard.record_failure(service_name)
        DEPENDENCY_ERRORS.labels(settings.service_name, service_name).inc()
        raise UpstreamError() from exc

    if response.status_code >= 500:
        await response.aclose()
        await guard.record_failure(service_name)
        DEPENDENCY_ERRORS.labels(settings.service_name, service_name).inc()
        raise UpstreamError()

    await guard.record_success(service_name)
    return StreamingResponse(
        _response_body(response),
        status_code=response.status_code,
        media_type=response.headers.get("content-type"),
        headers=filter_response_headers(response.headers),
    )
