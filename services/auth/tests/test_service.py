from uuid import uuid4

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from common.db import Base
from common.errors import UnauthorizedError
from services.auth.app.config import Settings
from services.auth.app.models import RefreshToken, User
from services.auth.app.service import AuthService, request_digest


class Pipeline:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def incr(self, key):
        return None

    def expire(self, key, ttl):
        return None

    async def execute(self):
        return [1, True, 1, True]


class Redis:
    def pipeline(self, transaction=True):
        return Pipeline()


@pytest_asyncio.fixture
async def context():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_private_key=private,
        jwt_public_key=public,
        bcrypt_rounds=4,
    )
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory, settings
    await engine.dispose()


@pytest.mark.asyncio
async def test_login_refresh_and_reuse_revokes_family(context):
    factory, settings = context
    async with factory() as session:
        service = AuthService(session, Redis(), settings)
        registration = {"login": "student", "password": "StrongPassword1"}
        await service.register(
            registration["login"],
            registration["password"],
            "register-key",
            request_digest(registration),
        )
        login_body = {"login": "student", "password": "StrongPassword1", "ip": "127.0.0.1"}
        pair = await service.login(
            "student",
            "StrongPassword1",
            "127.0.0.1",
            "login-key",
            request_digest(login_body),
        )
        refreshed = await service.refresh(
            pair["refresh_token"],
            "refresh-key",
            request_digest({"token": pair["refresh_token"]}),
        )
        assert refreshed["refresh_token"] != pair["refresh_token"]

        with pytest.raises(UnauthorizedError) as error:
            await service.refresh(
                pair["refresh_token"],
                "reuse-key",
                request_digest({"token": pair["refresh_token"]}),
            )
        assert error.value.error_code == "TOKEN_REUSE"

        active = await session.scalar(
            select(func.count())
            .select_from(RefreshToken)
            .where(RefreshToken.is_revoked.is_(False))
        )
        assert active == 0


@pytest.mark.asyncio
async def test_wrong_password_has_unified_error(context):
    factory, settings = context
    async with factory() as session:
        service = AuthService(session, Redis(), settings)
        with pytest.raises(UnauthorizedError) as error:
            await service.login(
                "unknown",
                "wrong",
                "127.0.0.1",
                "bad-login-key",
                request_digest({"login": "unknown", "password": "wrong"}),
            )
        assert error.value.message == "Неверный логин или пароль"


@pytest.mark.asyncio
async def test_logout_is_repeatable(context):
    factory, settings = context
    async with factory() as session:
        service = AuthService(session, Redis(), settings)
        await service.register(
            "logout-user",
            "StrongPassword1",
            "register-logout",
            request_digest({"login": "logout-user"}),
        )
        pair = await service.login(
            "logout-user",
            "StrongPassword1",
            "127.0.0.1",
            "login-logout",
            request_digest({"login": "logout-user", "password": "StrongPassword1"}),
        )
        digest = request_digest({"token": pair["refresh_token"]})
        first = await service.logout(pair["refresh_token"], "logout-key", digest)
        second = await service.logout(pair["refresh_token"], "logout-key", digest)
        assert first == second == {"status": "logged_out"}
