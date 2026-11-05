from fastapi import Request

from gateway.app.config import Settings, get_settings
from gateway.app.core.errors import RateLimitError
from gateway.app.core.rate_limit import check_rate_limit
from gateway.app.core.security import get_current_user


async def require_user(request: Request) -> None:
    settings: Settings = get_settings()
    user_id = get_current_user(request, settings)
    allowed, remaining = await check_rate_limit(
        request.app.state.redis,
        user_id,
        settings.rate_limit_per_user_per_minute,
        settings.rate_limit_window_seconds,
    )
    request.state.rate_limit_remaining = remaining
    if not allowed:
        raise RateLimitError(settings.rate_limit_window_seconds)


async def proxy_to(
    request: Request,
    service_name: str,
    upstream_path: str,
):
    from gateway.app.core.proxy import proxy_request

    settings = get_settings()
    return await proxy_request(
        request,
        f"{settings.service_urls[service_name]}{upstream_path}",
        service_name,
        settings,
    )


def mark_anonymous(request: Request) -> None:
    request.state.user_id = "00000000-0000-0000-0000-000000000000"
    request.state.user_roles = ()
