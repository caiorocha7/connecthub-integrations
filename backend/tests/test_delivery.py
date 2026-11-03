"""Worker delivery: success, retries with backoff, exhaustion, error classification, claim/lock."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import timedelta

import httpx
from sqlalchemy import select, update

from app.models import Delivery, DeliveryAttempt, Event, OutboxMessage, OutboxStatus
from app.services.common import utcnow
from app.services.delivery import process_delivery
from tests.conftest import mock_client


def _delivery_id(session_factory, event_id: str) -> uuid.UUID:  # type: ignore[no-untyped-def]
    with session_factory() as db:
        return db.scalar(select(Delivery.id).where(Delivery.event_id == uuid.UUID(event_id)))  # type: ignore[return-value]


def _make_due(session_factory, delivery_id: uuid.UUID) -> None:  # type: ignore[no-untyped-def]
    with session_factory() as db:
        db.execute(update(Delivery).where(Delivery.id == delivery_id).values(next_attempt_at=utcnow()))
        db.commit()


def _run(session_factory, delivery_id, client, worker="w1"):  # type: ignore[no-untyped-def]
    return process_delivery(
        delivery_id, session_factory=session_factory, client=client, worker_id=worker, rng=lambda: 0.0
    )


def test_successful_delivery_records_attempt_and_headers(
    admin, make_setup, send_webhook, session_factory
) -> None:  # type: ignore[no-untyped-def]
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    setup = make_setup(admin)
    event_id = send_webhook(setup, {"id": "evt-1", "amount": 5}).json()["event_id"]
    did = _delivery_id(session_factory, event_id)

    assert _run(session_factory, did, mock_client(handler)) == "succeeded"
    req = seen[0]
    assert json.loads(req.content) == {"id": "evt-1", "amount": 5}
    assert req.headers["X-ConnectHub-Event-Id"] == "evt-1"
    assert req.headers["Idempotency-Key"] == str(did)
    assert req.headers["X-ConnectHub-Attempt"] == "1"

    with session_factory() as db:
        d = db.get(Delivery, did)
        assert d.status == "SUCCEEDED" and d.attempt_count == 1 and d.succeeded_at is not None
        assert d.locked_by is None
        attempts = db.scalars(select(DeliveryAttempt).where(DeliveryAttempt.delivery_id == did)).all()
        assert len(attempts) == 1 and attempts[0].outcome == "SUCCESS" and attempts[0].status_code == 200
        assert attempts[0].duration_ms is not None
        assert db.get(Event, uuid.UUID(event_id)).status == "SUCCEEDED"


def test_5xx_retries_with_backoff_then_exhausts(admin, make_setup, send_webhook, session_factory) -> None:  # type: ignore[no-untyped-def]
    client = mock_client(lambda r: httpx.Response(500, text="boom"))
    setup = make_setup(admin, max_attempts=3)
    event_id = send_webhook(setup, {"id": "evt-500"}).json()["event_id"]
    did = _delivery_id(session_factory, event_id)

    before = utcnow()
    assert _run(session_factory, did, client) == "retrying"
    with session_factory() as db:
        d = db.get(Delivery, did)
        assert d.status == "RETRYING" and d.attempt_count == 1
        # equal-jitter backoff with rng=0 -> base/2 = 1s
        assert d.next_attempt_at >= before + timedelta(seconds=1)
        scheduled = db.scalars(
            select(OutboxMessage).where(
                OutboxMessage.aggregate_id == did, OutboxMessage.status == OutboxStatus.PENDING
            )
        ).all()
        # one from ingest (not yet published in tests) + one scheduled retry
        assert any(m.available_at == d.next_attempt_at for m in scheduled)
        assert db.get(Event, uuid.UUID(event_id)).status == "RETRYING"

    # not due yet -> claim refuses
    with session_factory() as db:
        db.execute(
            update(Delivery).where(Delivery.id == did).values(next_attempt_at=utcnow() + timedelta(minutes=1))
        )
        db.commit()
    assert _run(session_factory, did, client) == "skipped"

    _make_due(session_factory, did)
    assert _run(session_factory, did, client) == "retrying"
    _make_due(session_factory, did)
    assert _run(session_factory, did, client) == "failed"
    with session_factory() as db:
        d = db.get(Delivery, did)
        assert d.status == "FAILED" and d.attempt_count == 3 and d.last_status_code == 500
        attempts = db.scalars(
            select(DeliveryAttempt)
            .where(DeliveryAttempt.delivery_id == did)
            .order_by(DeliveryAttempt.attempt_number)
        ).all()
        assert [a.attempt_number for a in attempts] == [1, 2, 3]
        assert all(a.error_type == "http_5xx" for a in attempts)
        assert attempts[-1].next_retry_at is None
        assert db.get(Event, uuid.UUID(event_id)).status == "FAILED"
    # terminal: further messages are no-ops
    assert _run(session_factory, did, client) == "skipped"


def test_429_respects_retry_after(admin, make_setup, send_webhook, session_factory) -> None:  # type: ignore[no-untyped-def]
    client = mock_client(lambda r: httpx.Response(429, headers={"Retry-After": "30"}))
    setup = make_setup(admin)
    did = _delivery_id(session_factory, send_webhook(setup, {"id": "e429"}).json()["event_id"])
    before = utcnow()
    assert _run(session_factory, did, client) == "retrying"
    with session_factory() as db:
        d = db.get(Delivery, did)
        assert d.next_attempt_at >= before + timedelta(seconds=30)
        assert (
            db.scalar(select(DeliveryAttempt.error_type).where(DeliveryAttempt.delivery_id == did))
            == "http_429"
        )


def test_timeout_and_network_errors_are_retryable(admin, make_setup, send_webhook, session_factory) -> None:  # type: ignore[no-untyped-def]
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    def network_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    setup = make_setup(admin)
    d1 = _delivery_id(session_factory, send_webhook(setup, {"id": "t"}).json()["event_id"])
    d2 = _delivery_id(session_factory, send_webhook(setup, {"id": "n"}).json()["event_id"])
    assert _run(session_factory, d1, mock_client(timeout_handler)) == "retrying"
    assert _run(session_factory, d2, mock_client(network_handler)) == "retrying"
    with session_factory() as db:
        assert (
            db.scalar(select(DeliveryAttempt.error_type).where(DeliveryAttempt.delivery_id == d1))
            == "timeout"
        )
        assert (
            db.scalar(select(DeliveryAttempt.error_type).where(DeliveryAttempt.delivery_id == d2))
            == "network_error"
        )


def test_4xx_and_redirect_are_permanent(admin, make_setup, send_webhook, session_factory) -> None:  # type: ignore[no-untyped-def]
    setup = make_setup(admin, max_attempts=5)
    d1 = _delivery_id(session_factory, send_webhook(setup, {"id": "400"}).json()["event_id"])
    d2 = _delivery_id(session_factory, send_webhook(setup, {"id": "302"}).json()["event_id"])
    assert _run(session_factory, d1, mock_client(lambda r: httpx.Response(400))) == "failed"
    redirect = mock_client(lambda r: httpx.Response(302, headers={"Location": "http://169.254.169.254/"}))
    assert _run(session_factory, d2, redirect) == "failed"
    with session_factory() as db:
        assert db.get(Delivery, d1).attempt_count == 1
        assert (
            db.scalar(select(DeliveryAttempt.error_type).where(DeliveryAttempt.delivery_id == d2))
            == "redirect_blocked"
        )


def test_claim_prevents_concurrent_double_delivery(admin, make_setup, send_webhook, session_factory) -> None:  # type: ignore[no-untyped-def]
    calls: list[int] = []
    gate = threading.Event()

    def slow_handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        gate.wait(2)
        return httpx.Response(200)

    setup = make_setup(admin)
    did = _delivery_id(session_factory, send_webhook(setup, {"id": "race"}).json()["event_id"])
    results: list[str] = []

    def worker(name: str) -> None:
        results.append(_run(session_factory, did, mock_client(slow_handler), worker=name))

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    import time

    time.sleep(0.5)
    gate.set()
    for t in threads:
        t.join()
    assert sorted(results) == ["skipped", "skipped", "skipped", "succeeded"]
    assert len(calls) == 1
    with session_factory() as db:
        assert db.get(Delivery, did).attempt_count == 1


def test_transformation_applied_and_errors_are_permanent(
    client, admin, make_setup, send_webhook, session_factory
) -> None:  # type: ignore[no-untyped-def]
    base = f"/api/v1/orgs/{admin.org_id}/transform-rules"
    rule = client.post(
        base,
        json={
            "name": "ERP format",
            "mappings": [
                {"target": "orderId", "source": "id"},
                {"target": "total", "source": "amount", "type": "float", "required": True},
            ],
        },
        headers=admin.headers,
    ).json()
    setup = make_setup(admin, transform_rule_id=rule["id"])
    sent: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(204)

    ok = _delivery_id(session_factory, send_webhook(setup, {"id": "o1", "amount": "9.5"}).json()["event_id"])
    bad = _delivery_id(session_factory, send_webhook(setup, {"id": "o2"}).json()["event_id"])
    assert _run(session_factory, ok, mock_client(handler)) == "succeeded"
    assert sent == [{"orderId": "o1", "total": 9.5}]
    assert _run(session_factory, bad, mock_client(handler)) == "failed"
    with session_factory() as db:
        assert db.get(Delivery, ok).transformed_payload == {"orderId": "o1", "total": 9.5}
        att = db.scalar(select(DeliveryAttempt).where(DeliveryAttempt.delivery_id == bad))
        assert att.error_type == "transform_error" and att.status_code is None
    assert len(sent) == 1


def test_ssrf_revalidated_at_delivery_time(admin, make_setup, send_webhook, session_factory) -> None:  # type: ignore[no-untyped-def]
    from app.models import Destination

    setup = make_setup(admin)
    did = _delivery_id(session_factory, send_webhook(setup, {"id": "ssrf"}).json()["event_id"])
    with session_factory() as db:  # simulate a URL changed directly in the database
        db.execute(
            update(Destination)
            .where(Destination.id == uuid.UUID(setup.destination["id"]))
            .values(url="http://169.254.169.254/latest")
        )
        db.commit()
    called: list[int] = []
    assert (
        _run(session_factory, did, mock_client(lambda r: called.append(1) or httpx.Response(200))) == "failed"
    )
    assert called == []
