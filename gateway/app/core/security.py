import base64
from pathlib import Path
from typing import Any
from uuid import UUID

import jwt
from fastapi import Request

from gateway.app.config import Settings
from gateway.app.core.errors import UnauthorizedError


def _decode_key_value(value: str) -> str:
    if "BEGIN PUBLIC KEY" in value:
        return value
    try:
        return base64.b64decode(value).decode()
    except (ValueError, UnicodeDecodeError) as exc:
        raise UnauthorizedError(message="Ключ проверки токена повреждён") from exc


def _public_key(settings: Settings, kid: str | None = None) -> str:
    if kid and kid in settings.jwt_public_keys:
        return _decode_key_value(settings.jwt_public_keys[kid])
    if settings.jwt_public_key_path:
        return Path(settings.jwt_public_key_path).read_text(encoding="utf-8")
    value = settings.jwt_public_key
    if not value:
        raise UnauthorizedError(message="Ключ проверки токена не настроен")
    return _decode_key_value(value)


def decode_jwt(token: str, settings: Settings) -> dict[str, Any]:
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        if settings.jwt_public_keys and kid not in settings.jwt_public_keys:
            raise UnauthorizedError(message="Неизвестный ключ подписи")
        payload = jwt.decode(
            token,
            _public_key(settings, kid),
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={
                "require": ["sub", "exp", "iat", "jti"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_nbf": True,
            },
        )
        UUID(str(payload["sub"]))
        if not isinstance(payload.get("roles", []), list):
            raise ValueError("roles")
        return payload
    except UnauthorizedError:
        raise
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise UnauthorizedError(message="Токен недействителен или просрочен") from exc


def get_current_user(request: Request, settings: Settings) -> UUID:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise UnauthorizedError()
    payload = decode_jwt(token, settings)
    request.state.user_id = UUID(str(payload["sub"]))
    request.state.user_roles = tuple(str(role) for role in payload.get("roles", []))
    request.state.token_jti = payload["jti"]
    return request.state.user_id
