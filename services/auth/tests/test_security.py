from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from services.auth.app.config import Settings
from services.auth.app.security import decode_refresh, hash_password, issue_token_pair, jwks, verify_password


def settings_with_keys() -> Settings:
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
    return Settings(jwt_private_key=private, jwt_public_key=public, bcrypt_rounds=4)


def test_password_hash_is_verified():
    digest = hash_password("StrongPassword1", 4)
    assert verify_password("StrongPassword1", digest) is True
    assert verify_password("wrong", digest) is False


def test_refresh_contains_family_and_jwks_has_active_key():
    settings = settings_with_keys()
    family_id = uuid4()
    response, refresh, _ = issue_token_pair(uuid4(), ["user"], family_id, settings)
    payload = decode_refresh(refresh, settings)
    assert payload["family_id"] == str(family_id)
    assert response["token_type"] == "bearer"
    assert jwks(settings)["keys"][0]["kid"] == settings.jwt_active_kid
