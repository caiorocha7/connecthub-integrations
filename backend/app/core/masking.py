"""Recursive masking of sensitive values before exposing payloads through the API."""

from __future__ import annotations

from typing import Any

MASK = "***"
SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "card_number",
    "cardnumber",
    "credit_card",
    "cvv",
    "cvc",
    "cpf",
    "ssn",
    "signature",
)


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def mask_sensitive(value: Any, depth: int = 0) -> Any:
    if depth > 32:
        return value
    if isinstance(value, dict):
        return {
            k: (MASK if isinstance(k, str) and is_sensitive_key(k) else mask_sensitive(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [mask_sensitive(v, depth + 1) for v in value]
    return value
