import asyncio
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from gateway.app.config import Settings
from gateway.app.core.proxy import proxy_request
from common.errors import BadRequestError, ServiceUnavailableError, UpstreamError
from gateway.tests.conftest import request_with_app


class Guard:
    def __init__(self, reject=False):
        self.reject = reject
        self.failures = 0

    async def should_reject_fast(self, service_name):
        return self.reject

    async def record_success(self, service_name):
        return None

    async def record_failure(self, service_name):
        self.failures += 1


class Client:
    def __init__(self, cancelled=False):
        self.cancelled = cancelled
        self.outgoing = None

    def build_request(self, method, url, **kwargs):
        return httpx.Request(method, url, **kwargs)

    async def send(self, request, stream=False):
        self.outgoing = request
        if self.cancelled:
            raise asyncio.CancelledError()
        return httpx.Response(
            200,
            content=b'{"ok":true}',
            headers={"Content-Type": "application/json", "Server": "hidden"},
            request=request,
        )


@pytest.mark.asyncio
async def test_proxy_adds_internal_identity_and_filters_headers():
    app = FastAPI()
    client = Client()
    app.state.http_client = client
    app.state.availability_guard = Guard()
    request = await request_with_app(app)
    request.state.user_id = uuid4()
    request.state.user_roles = ("user",)

    response = await proxy_request(
        request,
        "http://accounts:8000/accounts",
        "accounts",
        Settings(),
    )

    assert client.outgoing.headers["X-User-Id"] == str(request.state.user_id)
    assert client.outgoing.headers["X-User-Roles"] == "user"
    assert client.outgoing.headers["X-Client-Ip"] == "127.0.0.1"
    assert "Authorization" not in client.outgoing.headers
    assert "server" not in response.headers
    chunks = [chunk async for chunk in response.body_iterator]
    assert b"".join(chunks) == b'{"ok":true}'


@pytest.mark.asyncio
async def test_client_disconnect_cancels_upstream_request():
    app = FastAPI()
    app.state.http_client = Client(cancelled=True)
    app.state.availability_guard = Guard()
    request = await request_with_app(app)
    request.state.user_id = uuid4()
    request.state.user_roles = ()

    with pytest.raises(asyncio.CancelledError):
        await proxy_request(
            request,
            "http://accounts:8000/accounts",
            "accounts",
            Settings(),
        )


@pytest.mark.asyncio
async def test_unavailable_service_is_rejected_before_request():
    app = FastAPI()
    app.state.http_client = Client()
    app.state.availability_guard = Guard(reject=True)
    request = await request_with_app(app)
    request.state.user_id = uuid4()
    request.state.user_roles = ()
    with pytest.raises(ServiceUnavailableError):
        await proxy_request(request, "http://accounts/accounts", "accounts", Settings())


@pytest.mark.asyncio
async def test_large_body_is_rejected():
    app = FastAPI()
    app.state.http_client = Client()
    app.state.availability_guard = Guard()
    request = await request_with_app(app, body=b"x" * 1025)
    request.state.user_id = uuid4()
    request.state.user_roles = ()
    with pytest.raises(BadRequestError):
        await proxy_request(
            request,
            "http://accounts/accounts",
            "accounts",
            Settings(max_request_body_bytes=1024),
        )


@pytest.mark.asyncio
async def test_server_error_records_failure():
    class ServerErrorClient(Client):
        async def send(self, request, stream=False):
            return httpx.Response(503, request=request)

    app = FastAPI()
    app.state.http_client = ServerErrorClient()
    guard = Guard()
    app.state.availability_guard = guard
    request = await request_with_app(app)
    request.state.user_id = uuid4()
    request.state.user_roles = ()
    with pytest.raises(UpstreamError):
        await proxy_request(request, "http://accounts/accounts", "accounts", Settings())
    assert guard.failures == 1
