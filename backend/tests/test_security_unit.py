"""Unit tests: HMAC, masking, SSRF protection, secret encryption, backoff."""

from __future__ import annotations

import pytest

from app.core.masking import mask_sensitive
from app.core.security import (
    build_signature_header,
    compute_signature,
    decrypt_secret,
    encrypt_secret,
    verify_signature,
)
from app.core.ssrf import UnsafeURLError, assert_safe_url
from app.services.delivery import compute_backoff


def test_hmac_signature_roundtrip_and_tampering() -> None:
    body = b'{"id":"evt_1","amount":10}'
    header = build_signature_header("whsec_test", "1700000000", body)
    assert header.startswith("v1=")
    assert verify_signature(["whsec_test"], "1700000000", body, header)
    assert not verify_signature(["whsec_test"], "1700000001", body, header)  # timestamp is signed
    assert not verify_signature(["whsec_test"], "1700000000", body + b" ", header)  # raw body
    assert not verify_signature(["other"], "1700000000", body, header)
    assert not verify_signature(["whsec_test"], "1700000000", body, "sha1=abc")
    # several candidate secrets (rotation) and several signatures in the header
    multi = f"v1=deadbeef, v1={compute_signature('new', '1', body)}"
    assert verify_signature(["old", "new"], "1", body, multi)


def test_secret_encryption_roundtrip() -> None:
    token = encrypt_secret("whsec_abc")
    assert "whsec_abc" not in token
    assert decrypt_secret(token) == "whsec_abc"


def test_mask_sensitive_nested() -> None:
    data = {
        "user": {"email": "a@b.com", "password": "x", "api_key": "k"},
        "items": [{"card_number": "4111", "sku": "A1"}],
        "Authorization": "Bearer t",
    }
    masked = mask_sensitive(data)
    assert masked["user"] == {"email": "a@b.com", "password": "***", "api_key": "***"}
    assert masked["items"][0] == {"card_number": "***", "sku": "A1"}
    assert masked["Authorization"] == "***"
    assert data["user"]["password"] == "x"  # original untouched


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://10.0.0.5/hook",
        "http://192.168.1.10/hook",
        "http://[::1]/hook",
        "http://0.0.0.0/hook",
        "ftp://example.com/file",
        "http://user:pass@example.com/",
        "file:///etc/passwd",
    ],
)
def test_ssrf_blocks_internal_targets(url: str) -> None:
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


def test_ssrf_allowlist_and_public_addresses() -> None:
    assert_safe_url("http://127.0.0.1:8131/hooks/demo")  # allow-listed in tests
    assert_safe_url("https://8.8.8.8/webhook")  # public literal
    with pytest.raises(UnsafeURLError):
        assert_safe_url("http://127.0.0.2/x")  # not in the allow-list


def test_backoff_is_exponential_with_jitter_and_capped() -> None:
    low = [compute_backoff(n, rng=lambda: 0.0) for n in range(1, 6)]
    high = [compute_backoff(n, rng=lambda: 1.0) for n in range(1, 6)]
    assert low == [1.0, 2.0, 4.0, 8.0, 16.0]
    assert high == [2.0, 4.0, 8.0, 16.0, 32.0]
    assert compute_backoff(30, rng=lambda: 1.0) == 300.0  # capped at RETRY_MAX_SECONDS
    assert compute_backoff(1, retry_after=20, rng=lambda: 0.0) == 20.0  # honours Retry-After
