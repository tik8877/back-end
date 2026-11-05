import base64
import hashlib
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import bcrypt
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from jwt.utils import base64url_encode

from common.time import utc_now
from services.auth.app.config import Settings


DUMMY_HASH = bcrypt.hashpw(b"not-a-user-password", bcrypt.gensalt(rounds=12))


def hash_password(password: str, rounds: int) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=rounds)).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    encoded_hash = password_hash.encode() if password_hash else DUMMY_HASH
    try:
        return bcrypt.checkpw(password.encode(), encoded_hash)
    except ValueError:
        bcrypt.checkpw(password.encode(), DUMMY_HASH)
        return False


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _read_key(value: str, path: Path | None) -> str:
    if path:
        return path.read_text(encoding="utf-8")
    if "BEGIN" in value:
        return value
    return base64.b64decode(value).decode() if value else ""


def private_key(settings: Settings) -> str:
    return _read_key(settings.jwt_private_key, settings.jwt_private_key_path)


def public_key(settings: Settings) -> str:
    if settings.jwt_public_key or settings.jwt_public_key_path:
        return _read_key(settings.jwt_public_key, settings.jwt_public_key_path)
    key = serialization.load_pem_private_key(private_key(settings).encode(), password=None)
    return key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


def verification_keys(settings: Settings) -> dict[str, str]:
    keys = {
        kid: _read_key(value, None) for kid, value in settings.jwt_public_keys.items()
    }
    keys.setdefault(settings.jwt_active_kid, public_key(settings))
    return keys


def issue_token_pair(
    user_id: UUID,
    roles: list[str],
    family_id: UUID,
    settings: Settings,
) -> tuple[dict[str, Any], str, UUID]:
    now = utc_now()
    access_jti = uuid4()
    refresh_jti = uuid4()
    headers = {"kid": settings.jwt_active_kid, "typ": "JWT"}
    access = jwt.encode(
        {
            "sub": str(user_id),
            "roles": roles,
            "jti": str(access_jti),
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(seconds=settings.access_token_ttl_seconds),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "token_type": "access",
        },
        private_key(settings),
        algorithm=settings.jwt_algorithm,
        headers=headers,
    )
    refresh = jwt.encode(
        {
            "sub": str(user_id),
            "jti": str(refresh_jti),
            "family_id": str(family_id),
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(seconds=settings.refresh_token_ttl_seconds),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "token_type": "refresh",
        },
        private_key(settings),
        algorithm=settings.jwt_algorithm,
        headers=headers,
    )
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": settings.access_token_ttl_seconds,
    }, refresh, refresh_jti


def decode_refresh(token: str, settings: Settings) -> dict[str, Any]:
    kid = jwt.get_unverified_header(token).get("kid")
    keys = verification_keys(settings)
    if kid not in keys:
        raise jwt.InvalidTokenError("unknown key")
    payload = jwt.decode(
        token,
        keys[kid],
        algorithms=[settings.jwt_algorithm],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
        options={"require": ["sub", "jti", "family_id", "exp", "iat"]},
    )
    if payload.get("token_type") != "refresh":
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def jwks(settings: Settings) -> dict:
    result = []
    for kid, value in verification_keys(settings).items():
        key = serialization.load_pem_public_key(value.encode())
        if not isinstance(key, RSAPublicKey):
            raise ValueError("Поддерживаются только RSA-ключи")
        numbers = key.public_numbers()
        exponent = numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")
        modulus = numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")
        result.append(
            {
                "kty": "RSA",
                "use": "sig",
                "alg": settings.jwt_algorithm,
                "kid": kid,
                "n": base64url_encode(modulus).decode(),
                "e": base64url_encode(exponent).decode(),
            }
        )
    return {"keys": result}
