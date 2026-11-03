"""Password hashing, JWT tokens, secret generation/encryption and HMAC signatures."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


# ---------------------------------------------------------------- JWT access tokens
class TokenError(Exception):
    pass


def create_access_token(user_id: uuid.UUID) -> tuple[str, int]:
    settings = get_settings()
    expires_in = settings.access_token_expire_minutes * 60
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "type"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError("invalid or expired token") from exc
    if payload.get("type") != "access":
        raise TokenError("invalid token type")
    return payload


# ---------------------------------------------------------------- opaque refresh tokens
def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------- endpoint secrets
def generate_signing_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def generate_public_id() -> str:
    return "ep_" + secrets.token_hex(10)


@lru_cache
def _fernet() -> Fernet:
    settings = get_settings()
    if settings.field_encryption_key:
        return Fernet(settings.field_encryption_key.encode())
    derived = hashlib.sha256(("connecthub-field-key:" + settings.secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:  # pragma: no cover - indicates key misconfiguration
        raise RuntimeError("unable to decrypt stored secret (encryption key changed?)") from exc


def mask_secret(value: str) -> str:
    if len(value) <= 12:
        return "****"
    return value[:8] + "…" + value[-4:]


# ---------------------------------------------------------------- HMAC signatures
SIGNATURE_VERSION = "v1"


def compute_signature(secret: str, timestamp: str, body: bytes) -> str:
    message = timestamp.encode() + b"." + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def build_signature_header(secret: str, timestamp: str, body: bytes) -> str:
    return f"{SIGNATURE_VERSION}={compute_signature(secret, timestamp, body)}"


def parse_signature_header(header: str) -> list[str]:
    """Accept ``v1=<hex>`` (optionally several, comma separated) and return the digests."""
    digests: list[str] = []
    for part in header.split(","):
        version, _, digest = part.strip().partition("=")
        if version == SIGNATURE_VERSION and digest:
            digests.append(digest.strip())
    return digests


def verify_signature(secrets_to_try: list[str], timestamp: str, body: bytes, header: str) -> bool:
    provided = parse_signature_header(header)
    if not provided:
        return False
    matched = False
    for secret in secrets_to_try:
        expected = compute_signature(secret, timestamp, body)
        for digest in provided:
            # constant-time compare; keep iterating to avoid early-exit timing differences
            if hmac.compare_digest(expected.encode(), digest.encode()):
                matched = True
    return matched
