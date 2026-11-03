"""Delivery execution with claim/lock, error classification, exponential backoff and jitter.

Flow for one task execution:

1. **Claim** (short transaction): a conditional ``UPDATE ... WHERE status IN (PENDING, RETRYING)
   AND next_attempt_at <= now RETURNING`` moves the delivery to PROCESSING and increments
   ``attempt_count``. Only one worker can win the claim; duplicate broker messages become no-ops.
   The attempt row is inserted with a unique ``(delivery_id, attempt_number)``.
2. **HTTP call** outside of any database transaction, with timeout and no redirects.
3. **Finalize** (short transaction, guarded by ``locked_by``): record the attempt result and
   decide SUCCEEDED / RETRYING (+ outbox message scheduled at ``next_attempt_at``) / FAILED.
"""

from __future__ import annotations

import json
import logging
import random
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.logging import log_context
from app.core.security import build_signature_header, decrypt_secret
from app.core.ssrf import UnsafeURLError, assert_safe_url
from app.models import (
    AttemptOutcome,
    AttemptTrigger,
    Delivery,
    DeliveryAttempt,
    DeliveryStatus,
    Destination,
    Event,
    TransformRule,
)
from app.services.common import refresh_event_status, utcnow
from app.services.outbox import enqueue_delivery
from app.services.transform import RuleValidationError, TransformError, transform_payload

logger = logging.getLogger(__name__)

MAX_TIMEOUT_SECONDS = 60
USER_AGENT = "ConnectHub-Webhooks/1.0"


@dataclass
class HttpOutcome:
    outcome: AttemptOutcome
    status_code: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    response_excerpt: str | None = None
    duration_ms: int | None = None
    retry_after: float | None = None


@dataclass
class ClaimedDelivery:
    delivery_id: uuid.UUID
    event_id: uuid.UUID
    attempt_id: uuid.UUID
    attempt_number: int
    url: str
    method: str
    headers: dict[str, str]
    timeout: int
    signing_secret: str | None
    external_event_id: str
    payload: Any
    transform_error: str | None


def compute_backoff(
    attempt_number: int,
    retry_after: float | None = None,
    *,
    rng: Callable[[], float] = random.random,
) -> float:
    """Exponential backoff with "equal jitter": delay in [cap/2, cap]."""
    settings = get_settings()
    exp = float(settings.retry_base_seconds) * float(2 ** max(attempt_number - 1, 0))
    capped = min(settings.retry_max_seconds, exp)
    delay = capped / 2 + rng() * capped / 2
    if retry_after is not None and retry_after > 0:
        delay = max(delay, min(retry_after, settings.retry_max_seconds))
    return delay


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        return None


def classify_response(response: httpx.Response, duration_ms: int) -> HttpOutcome:
    settings = get_settings()
    excerpt = response.text[: settings.response_body_excerpt_bytes] if response.content else None
    code = response.status_code
    if 200 <= code < 300:
        return HttpOutcome(AttemptOutcome.SUCCESS, code, None, None, excerpt, duration_ms)
    if code == 429:
        return HttpOutcome(
            AttemptOutcome.RETRYABLE_ERROR,
            code,
            "http_429",
            "destino aplicou rate limit (429)",
            excerpt,
            duration_ms,
            _parse_retry_after(response.headers.get("retry-after")),
        )
    if code >= 500 or code in (408, 425):
        return HttpOutcome(
            AttemptOutcome.RETRYABLE_ERROR,
            code,
            "http_5xx" if code >= 500 else f"http_{code}",
            f"destino respondeu HTTP {code}",
            excerpt,
            duration_ms,
        )
    if 300 <= code < 400:
        return HttpOutcome(
            AttemptOutcome.PERMANENT_ERROR,
            code,
            "redirect_blocked",
            "redirecionamentos não são seguidos por segurança",
            excerpt,
            duration_ms,
        )
    return HttpOutcome(
        AttemptOutcome.PERMANENT_ERROR,
        code,
        "http_4xx",
        f"destino rejeitou a requisição com HTTP {code}",
        excerpt,
        duration_ms,
    )


def _claim(
    session_factory: sessionmaker[Session], delivery_id: uuid.UUID, worker_id: str
) -> ClaimedDelivery | None:
    settings = get_settings()
    with session_factory() as db:
        now = utcnow()
        lock_until = now + timedelta(seconds=MAX_TIMEOUT_SECONDS + settings.delivery_lock_margin_seconds)
        delivery = db.execute(
            select(Delivery)
            .where(
                Delivery.id == delivery_id,
                Delivery.status.in_([DeliveryStatus.PENDING, DeliveryStatus.RETRYING]),
                or_(
                    Delivery.next_attempt_at.is_(None),
                    Delivery.next_attempt_at <= now + timedelta(seconds=1),
                ),
            )
            .with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        if delivery is None:
            db.rollback()
            return None
        trigger = delivery.next_trigger
        delivery.status = DeliveryStatus.PROCESSING
        delivery.locked_by = worker_id
        delivery.locked_until = lock_until
        delivery.attempt_count += 1
        delivery.next_trigger = AttemptTrigger.AUTO
        attempt_number = delivery.attempt_count
        event = db.get(Event, delivery.event_id)
        destination = db.get(Destination, delivery.destination_id)
        assert event is not None and destination is not None

        attempt = DeliveryAttempt(
            id=uuid.uuid4(),
            organization_id=delivery.organization_id,
            delivery_id=delivery.id,
            attempt_number=attempt_number,
            trigger=trigger,
            outcome=AttemptOutcome.IN_PROGRESS,
            worker_id=worker_id,
            request_url=destination.url,
            request_method=str(destination.method),
            started_at=now,
        )
        db.add(attempt)

        transform_error: str | None = None
        payload: Any = event.payload
        if delivery.transform_rule_id is not None:
            rule = db.get(TransformRule, delivery.transform_rule_id)
            if rule is not None:
                try:
                    payload = transform_payload(rule.mappings, rule.include_unmapped, event.payload)
                except (TransformError, RuleValidationError) as exc:
                    transform_error = str(exc)
                    payload = None
        delivery.transformed_payload = payload
        refresh_event_status(db, event.id)
        db.commit()

        signing_secret = (
            decrypt_secret(destination.signing_secret_encrypted)
            if destination.signing_secret_encrypted
            else None
        )
        return ClaimedDelivery(
            delivery_id=delivery.id,
            event_id=event.id,
            attempt_id=attempt.id,
            attempt_number=attempt_number,
            url=destination.url,
            method=str(destination.method),
            headers=dict(destination.headers or {}),
            timeout=destination.timeout_seconds,
            signing_secret=signing_secret,
            external_event_id=event.external_event_id,
            payload=payload,
            transform_error=transform_error,
        )


def _send(claim: ClaimedDelivery, client: httpx.Client) -> HttpOutcome:
    if claim.transform_error:
        return HttpOutcome(
            AttemptOutcome.PERMANENT_ERROR,
            error_type="transform_error",
            error_message=f"falha na transformação: {claim.transform_error}"[:1000],
        )
    try:
        assert_safe_url(claim.url)
    except UnsafeURLError as exc:
        return HttpOutcome(
            AttemptOutcome.PERMANENT_ERROR,
            error_type="ssrf_blocked",
            error_message=f"URL de destino bloqueada: {exc}",
        )

    body = json.dumps(claim.payload, separators=(",", ":"), ensure_ascii=False).encode()
    headers = {
        **claim.headers,
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "X-ConnectHub-Event-Id": claim.external_event_id,
        "X-ConnectHub-Delivery-Id": str(claim.delivery_id),
        "X-ConnectHub-Attempt": str(claim.attempt_number),
        "Idempotency-Key": str(claim.delivery_id),
    }
    if claim.signing_secret:
        ts = str(int(time.time()))
        headers["X-ConnectHub-Timestamp"] = ts
        headers["X-ConnectHub-Signature"] = build_signature_header(claim.signing_secret, ts, body)

    started = time.perf_counter()
    try:
        response = client.request(
            claim.method,
            claim.url,
            content=body,
            headers=headers,
            timeout=httpx.Timeout(claim.timeout),
            follow_redirects=False,
        )
    except httpx.TimeoutException:
        return HttpOutcome(
            AttemptOutcome.RETRYABLE_ERROR,
            error_type="timeout",
            error_message=f"tempo limite de {claim.timeout}s excedido",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except httpx.TransportError as exc:
        return HttpOutcome(
            AttemptOutcome.RETRYABLE_ERROR,
            error_type="network_error",
            error_message=f"erro de rede: {type(exc).__name__}",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    return classify_response(response, int((time.perf_counter() - started) * 1000))


def _finalize(
    session_factory: sessionmaker[Session],
    claim: ClaimedDelivery,
    result: HttpOutcome,
    worker_id: str,
    rng: Callable[[], float],
) -> str:
    with session_factory() as db:
        now = utcnow()
        attempt = db.get(DeliveryAttempt, claim.attempt_id)
        assert attempt is not None
        attempt.outcome = result.outcome
        attempt.status_code = result.status_code
        attempt.error_type = result.error_type
        attempt.error_message = result.error_message
        attempt.response_excerpt = result.response_excerpt
        attempt.duration_ms = result.duration_ms
        attempt.finished_at = now

        delivery = db.execute(
            select(Delivery)
            .where(
                Delivery.id == claim.delivery_id,
                Delivery.locked_by == worker_id,
                Delivery.status == DeliveryStatus.PROCESSING,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if delivery is None:
            # Lock expired and the recovery job took over; keep the attempt record only.
            db.commit()
            logger.warning("delivery lock lost before finalize")
            return "lock_lost"

        delivery.last_status_code = result.status_code
        delivery.locked_by = None
        delivery.locked_until = None
        if result.outcome == AttemptOutcome.SUCCESS:
            delivery.status = DeliveryStatus.SUCCEEDED
            delivery.succeeded_at = now
            delivery.next_attempt_at = None
            delivery.last_error = None
            final = "succeeded"
        elif (
            result.outcome == AttemptOutcome.RETRYABLE_ERROR
            and delivery.attempt_count < delivery.max_attempts
        ):
            delay = compute_backoff(delivery.attempt_count, result.retry_after, rng=rng)
            next_at = now + timedelta(seconds=delay)
            delivery.status = DeliveryStatus.RETRYING
            delivery.next_attempt_at = next_at
            delivery.last_error = result.error_message
            attempt.next_retry_at = next_at
            enqueue_delivery(db, delivery, available_at=next_at)
            final = "retrying"
        else:
            delivery.status = DeliveryStatus.FAILED
            delivery.failed_at = now
            delivery.next_attempt_at = None
            delivery.last_error = result.error_message
            final = "failed"
        refresh_event_status(db, delivery.event_id)
        db.commit()
        return final


def process_delivery(
    delivery_id: uuid.UUID,
    *,
    session_factory: sessionmaker[Session],
    client: httpx.Client,
    worker_id: str,
    rng: Callable[[], float] = random.random,
) -> str:
    """Execute one attempt of a delivery. Returns: skipped | succeeded | retrying | failed."""
    with log_context(delivery_id=delivery_id, worker_id=worker_id):
        claim = _claim(session_factory, delivery_id, worker_id)
        if claim is None:
            logger.info("delivery not claimable (already processed, locked or not due)")
            return "skipped"
        with log_context(event_id=claim.event_id, attempt=claim.attempt_number):
            result = _send(claim, client)
            final = _finalize(session_factory, claim, result, worker_id, rng)
            logger.info(
                "delivery attempt finished",
                extra={
                    "result": final,
                    "status_code": result.status_code,
                    "error_type": result.error_type,
                    "duration_ms": result.duration_ms,
                },
            )
            return final


def build_http_client() -> httpx.Client:
    return httpx.Client(
        follow_redirects=False,
        trust_env=False,
        headers={"User-Agent": USER_AGENT},
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
    )


def is_due(delivery: Delivery, now: datetime) -> bool:
    return delivery.next_attempt_at is None or delivery.next_attempt_at <= now
