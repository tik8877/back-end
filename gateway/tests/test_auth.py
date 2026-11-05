from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from common.errors import UnauthorizedError
from gateway.app.config import Settings
from gateway.app.core.security import decode_jwt
from gateway.app.core.security import get_current_user
from starlette.requests import Request


@pytest.fixture
def keys():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def token(private_key: bytes, expires_at: datetime) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(uuid4()),
            "roles": ["user"],
            "jti": str(uuid4()),
            "iat": now,
            "nbf": now,
            "exp": expires_at,
            "iss": "fpm-auth",
            "aud": "fpm-api",
        },
        private_key,
        algorithm="RS256",
    )


def test_valid_token(keys):
    private, public = keys
    settings = Settings(jwt_public_key=public.decode())
    payload = decode_jwt(token(private, datetime.now(UTC) + timedelta(minutes=5)), settings)
    assert payload["roles"] == ["user"]


def test_expired_token(keys):
    private, public = keys
    settings = Settings(jwt_public_key=public.decode())
    with pytest.raises(UnauthorizedError):
        decode_jwt(token(private, datetime.now(UTC) - timedelta(seconds=1)), settings)


def test_invalid_signature(keys):
    _, public = keys
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_private = other.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    settings = Settings(jwt_public_key=public.decode())
    with pytest.raises(UnauthorizedError):
        decode_jwt(token(other_private, datetime.now(UTC) + timedelta(minutes=5)), settings)


def test_base64_public_key_and_request_identity(keys):
    import base64

    private, public = keys
    value = token(private, datetime.now(UTC) + timedelta(minutes=5))
    settings = Settings(jwt_public_key=base64.b64encode(public).decode())
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"authorization", f"Bearer {value}".encode())],
        }
    )
    user_id = get_current_user(request, settings)
    assert user_id == request.state.user_id
    assert request.state.user_roles == ("user",)


def test_missing_authorization_is_rejected(keys):
    _, public = keys
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    with pytest.raises(UnauthorizedError):
        get_current_user(request, Settings(jwt_public_key=public.decode()))


def test_invalid_roles_are_rejected(keys):
    private, public = keys
    now = datetime.now(UTC)
    value = jwt.encode(
        {
            "sub": str(uuid4()),
            "roles": "user",
            "jti": str(uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=1),
            "iss": "fpm-auth",
            "aud": "fpm-api",
        },
        private,
        algorithm="RS256",
    )
    with pytest.raises(UnauthorizedError):
        decode_jwt(value, Settings(jwt_public_key=public.decode()))
