import hashlib
import json
from datetime import UTC, timedelta
from uuid import UUID, uuid4

import jwt
import structlog
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from common.errors import BadRequestError, RateLimitError, UnauthorizedError
from common.time import utc_now
from services.auth.app.config import Settings
from services.auth.app.models import AuthRequestResult, LoginAttempt, RefreshToken, User
from services.auth.app.security import (
    decode_refresh,
    hash_password,
    issue_token_pair,
    token_digest,
    verify_password,
)


def request_digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


class AuthService:
    def __init__(self, session: AsyncSession, redis: Redis, settings: Settings) -> None:
        self.session = session
        self.redis = redis
        self.settings = settings

    def _insert(self, model):
        dialect = self.session.bind.dialect.name if self.session.bind else "postgresql"
        return sqlite_insert(model) if dialect == "sqlite" else postgresql_insert(model)

    async def _existing(self, scope: str, key: str, digest: str) -> AuthRequestResult | None:
        row = await self.session.scalar(
            select(AuthRequestResult).where(
                AuthRequestResult.scope == scope,
                AuthRequestResult.idempotency_key == key,
            )
        )
        if row and row.request_hash != digest:
            raise BadRequestError("IDEMPOTENCY_KEY_REUSE", "Ключ уже использован")
        return row

    async def _limit_login(self, login: str, ip: str) -> None:
        window = self.settings.login_window_seconds
        slot = int(utc_now().timestamp()) // window
        login_hash = hashlib.sha256(login.lower().encode()).hexdigest()
        ip_hash = hashlib.sha256(ip.encode()).hexdigest()
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.incr(f"auth:ip:{ip_hash}:{slot}")
                pipe.expire(f"auth:ip:{ip_hash}:{slot}", window + 1)
                pipe.incr(f"auth:login:{login_hash}:{slot}")
                pipe.expire(f"auth:login:{login_hash}:{slot}", window + 1)
                ip_count, _, login_count, _ = await pipe.execute()
            if (
                int(ip_count) > self.settings.login_attempts_per_ip
                or int(login_count) > self.settings.login_attempts_per_login
            ):
                raise RateLimitError(window)
        except RateLimitError:
            raise
        except Exception as exc:
            structlog.get_logger().warning(
                "login_limit_storage_unavailable",
                details={"error_type": type(exc).__name__},
            )

    async def register(self, login: str, password: str, key: str, digest: str) -> dict:
        normalized = login.lower()
        async with self.session.begin():
            existing_result = await self._existing("register", key, digest)
            if existing_result:
                return existing_result.response_body or {"status": "registration_processed"}
            response = {"status": "registration_processed"}
            await self.session.execute(
                self._insert(User)
                .values(
                    id=uuid4(),
                    login=normalized,
                    password_hash=hash_password(password, self.settings.bcrypt_rounds),
                    roles=["user"],
                    is_active=True,
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
                .on_conflict_do_nothing(index_elements=[User.login])
            )
            await self.session.execute(
                self._insert(AuthRequestResult)
                .values(
                    id=uuid4(),
                    scope="register",
                    idempotency_key=key,
                    request_hash=digest,
                    response_body=response,
                    created_at=utc_now(),
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        AuthRequestResult.scope,
                        AuthRequestResult.idempotency_key,
                    ]
                )
            )
            saved = await self._existing("register", key, digest)
            if saved and saved.request_hash != digest:
                raise BadRequestError("IDEMPOTENCY_KEY_REUSE", "Ключ уже использован")
        return response

    async def login(self, login: str, password: str, ip: str, key: str, digest: str) -> dict:
        normalized = login.lower()
        async with self.session.begin():
            existing_result = await self._existing("login", key, digest)
        if existing_result:
            if existing_result.error_code:
                raise UnauthorizedError(message="Неверный логин или пароль")
            return existing_result.response_body or {}
        await self._limit_login(normalized, ip)
        failed = False
        response: dict = {}
        user: User | None = None
        async with self.session.begin():
            user = await self.session.scalar(select(User).where(User.login == normalized))
            valid = verify_password(password, user.password_hash if user else None)
            if not user or not valid or not user.is_active:
                self.session.add(LoginAttempt(ip=ip, login=normalized, success=False))
                self.session.add(
                    AuthRequestResult(
                        scope="login",
                        idempotency_key=key,
                        request_hash=digest,
                        error_code="INVALID_CREDENTIALS",
                    )
                )
                failed = True
            else:
                family_id = uuid4()
                response, refresh_raw, _ = issue_token_pair(
                    user.id, user.roles, family_id, self.settings
                )
                self.session.add_all(
                    [
                        LoginAttempt(ip=ip, login=normalized, success=True),
                        RefreshToken(
                            user_id=user.id,
                            token_hash=token_digest(refresh_raw),
                            family_id=family_id,
                            expires_at=utc_now()
                            + timedelta(seconds=self.settings.refresh_token_ttl_seconds),
                        ),
                        AuthRequestResult(
                            scope="login",
                            idempotency_key=key,
                            request_hash=digest,
                            response_body=response,
                        ),
                    ]
                )
        if failed or user is None:
            raise UnauthorizedError(message="Неверный логин или пароль")
        structlog.get_logger().info(
            "login_succeeded",
            user_id=str(user.id),
            details={"ip": ip, "timestamp": utc_now().isoformat()},
        )
        return response

    async def refresh(self, raw_token: str, key: str, digest: str) -> dict:
        async with self.session.begin():
            existing = await self._existing("refresh", key, digest)
        if existing:
            if existing.error_code:
                raise UnauthorizedError("TOKEN_REUSE", "Токен уже использован")
            return existing.response_body or {}
        try:
            payload = decode_refresh(raw_token, self.settings)
        except jwt.PyJWTError as exc:
            raise UnauthorizedError(message="Токен обновления недействителен") from exc
        compromised = False
        response: dict = {}
        async with self.session.begin():
            token = await self.session.scalar(
                select(RefreshToken)
                .where(RefreshToken.token_hash == token_digest(raw_token))
                .with_for_update()
            )
            token_expiry = token.expires_at if token else None
            if token_expiry and token_expiry.tzinfo is None:
                token_expiry = token_expiry.replace(tzinfo=UTC)
            if not token or token_expiry <= utc_now():
                raise UnauthorizedError(message="Токен обновления недействителен")
            if token.is_revoked:
                await self.session.execute(
                    update(RefreshToken)
                    .where(RefreshToken.family_id == token.family_id)
                    .values(is_revoked=True, revoked_at=utc_now())
                )
                self.session.add(
                    AuthRequestResult(
                        scope="refresh",
                        idempotency_key=key,
                        request_hash=digest,
                        error_code="TOKEN_REUSE",
                    )
                )
                compromised = True
            else:
                user = await self.session.get(User, token.user_id)
                if not user or not user.is_active:
                    raise UnauthorizedError()
                token.is_revoked = True
                token.revoked_at = utc_now()
                response, refresh_raw, _ = issue_token_pair(
                    user.id, user.roles, token.family_id, self.settings
                )
                self.session.add_all(
                    [
                        RefreshToken(
                            user_id=user.id,
                            token_hash=token_digest(refresh_raw),
                            family_id=token.family_id,
                            expires_at=utc_now()
                            + timedelta(seconds=self.settings.refresh_token_ttl_seconds),
                        ),
                        AuthRequestResult(
                            scope="refresh",
                            idempotency_key=key,
                            request_hash=digest,
                            response_body=response,
                        ),
                    ]
                )
        if compromised:
            raise UnauthorizedError("TOKEN_REUSE", "Токен уже использован")
        return response

    async def logout(self, raw_token: str, key: str, digest: str) -> dict:
        async with self.session.begin():
            existing = await self._existing("logout", key, digest)
        if existing:
            return existing.response_body or {"status": "logged_out"}
        async with self.session.begin():
            token = await self.session.scalar(
                select(RefreshToken)
                .where(RefreshToken.token_hash == token_digest(raw_token))
                .with_for_update()
            )
            if token and not token.is_revoked:
                token.is_revoked = True
                token.revoked_at = utc_now()
            response = {"status": "logged_out"}
            self.session.add(
                AuthRequestResult(
                    scope="logout",
                    idempotency_key=key,
                    request_hash=digest,
                    response_body=response,
                )
            )
        structlog.get_logger().info(
            "logout_completed", details={"timestamp": utc_now().isoformat()}
        )
        return response
