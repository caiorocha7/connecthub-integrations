"""Webhook ingestion: HMAC, replay window, limits, persistence, outbox and idempotency."""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import Delivery, Event, OutboxMessage, OutboxStatus
from tests.conftest import signed_headers


def _count(session_factory, model) -> int:  # type: ignore[no-untyped-def]
    with session_factory() as db:
        return int(db.scalar(select(func.count()).select_from(model)) or 0)


def test_valid_webhook_is_persisted_with_delivery_and_outbox(
    client: TestClient, admin, make_setup, send_webhook, session_factory, captured_dispatch
) -> None:  # type: ignore[no-untyped-def]
    setup = make_setup(admin)
    r = send_webhook(setup, {"id": "order-1001", "total": 10})
    assert r.status_code == 202
    body = r.json()
    assert body["duplicate"] is False and body["deliveries"] == 1
    assert body["external_event_id"] == "order-1001"

    with session_factory() as db:
        event = db.get(Event, body["event_id"])
        assert event is not None
        assert event.payload == {"id": "order-1001", "total": 10}
        assert event.event_id_source == "payload"
        assert "x-connecthub-signature" not in event.headers
        delivery = db.scalar(select(Delivery).where(Delivery.event_id == event.id))
        assert delivery is not None and delivery.status == "PENDING"
        msg = db.scalar(select(OutboxMessage).where(OutboxMessage.aggregate_id == delivery.id))
        assert msg is not None and msg.status == OutboxStatus.PENDING
    # API asked for an immediate (best-effort) dispatch of the outbox message
    assert captured_dispatch == [[msg.id]]


def test_duplicate_event_does_not_create_new_delivery(
    client: TestClient, admin, make_setup, send_webhook, session_factory, captured_dispatch
) -> None:  # type: ignore[no-untyped-def]
    setup = make_setup(admin)
    first = send_webhook(setup, {"id": "same-id", "v": 1})
    second = send_webhook(setup, {"id": "same-id", "v": 2})
    third = send_webhook(setup, {"other": True}, event_id="same-id")  # header takes precedence
    assert first.status_code == 202
    assert second.status_code == 200 and second.json()["duplicate"] is True
    assert third.status_code == 200 and third.json()["duplicate"] is True
    assert second.json()["event_id"] == first.json()["event_id"]
    assert _count(session_factory, Event) == 1
    assert _count(session_factory, Delivery) == 1
    assert _count(session_factory, OutboxMessage) == 1
    assert len(captured_dispatch) == 1
    with session_factory() as db:
        event = db.get(Event, first.json()["event_id"])
        assert event is not None and event.duplicate_count == 2


def test_same_event_id_on_different_endpoints_is_not_duplicate(
    admin, make_setup, send_webhook, session_factory
) -> None:  # type: ignore[no-untyped-def]
    a = make_setup(admin)
    b = make_setup(admin)
    assert send_webhook(a, {"id": "x"}).status_code == 202
    assert send_webhook(b, {"id": "x"}).status_code == 202
    assert _count(session_factory, Event) == 2


def test_event_id_fallback_to_body_hash(admin, make_setup, send_webhook) -> None:  # type: ignore[no-untyped-def]
    setup = make_setup(admin)
    r1 = send_webhook(setup, {"no_id": 1})
    r2 = send_webhook(setup, {"no_id": 1})
    assert r1.json()["external_event_id"].startswith("sha256:")
    assert r2.json()["duplicate"] is True


def test_invalid_signatures_are_rejected(client: TestClient, admin, make_setup, session_factory) -> None:  # type: ignore[no-untyped-def]
    setup = make_setup(admin)
    url = f"/api/v1/ingest/{setup.endpoint['public_id']}"
    body = json.dumps({"id": "e1"}).encode()

    missing = client.post(url, content=body, headers={"Content-Type": "application/json"})
    assert missing.status_code == 401

    wrong_secret = client.post(url, content=body, headers=signed_headers("whsec_wrong", body))
    assert wrong_secret.status_code == 401 and wrong_secret.json()["detail"] == "assinatura inválida"

    tampered_headers = signed_headers(setup.secret, body)
    tampered = client.post(url, content=body.replace(b"e1", b"e2"), headers=tampered_headers)
    assert tampered.status_code == 401

    old = client.post(
        url, content=body, headers=signed_headers(setup.secret, body, ts=int(time.time()) - 3600)
    )
    assert old.status_code == 401 and "replay" in old.json()["detail"]

    assert _count(session_factory, Event) == 0


def test_request_validation(client: TestClient, admin, make_setup) -> None:  # type: ignore[no-untyped-def]
    setup = make_setup(admin)
    url = f"/api/v1/ingest/{setup.endpoint['public_id']}"

    not_json = b"not json"
    r = client.post(url, content=not_json, headers=signed_headers(setup.secret, not_json))
    assert r.status_code == 400

    scalar = b"42"
    assert client.post(url, content=scalar, headers=signed_headers(setup.secret, scalar)).status_code == 400

    wrong_type = client.post(
        url, content=b"{}", headers={**signed_headers(setup.secret, b"{}"), "Content-Type": "text/plain"}
    )
    assert wrong_type.status_code == 415

    big = json.dumps({"id": "big", "data": "x" * 300_000}).encode()
    assert client.post(url, content=big, headers=signed_headers(setup.secret, big)).status_code == 413

    assert (
        client.post(
            "/api/v1/ingest/ep_doesnotexist", content=b"{}", headers=signed_headers("s", b"{}")
        ).status_code
        == 404
    )


def test_inactive_endpoint_rejects(client: TestClient, admin, make_setup, send_webhook) -> None:  # type: ignore[no-untyped-def]
    setup = make_setup(admin)
    client.patch(
        f"/api/v1/orgs/{admin.org_id}/endpoints/{setup.endpoint['id']}",
        json={"is_active": False},
        headers=admin.headers,
    )
    assert send_webhook(setup, {"id": "1"}).status_code == 404


def test_secret_rotation_with_grace_period(client: TestClient, admin, make_setup, send_webhook) -> None:  # type: ignore[no-untyped-def]
    setup = make_setup(admin)
    base = f"/api/v1/orgs/{admin.org_id}/endpoints/{setup.endpoint['id']}"
    rotated = client.post(f"{base}/rotate-secret", json={"grace_period_minutes": 30}, headers=admin.headers)
    assert rotated.status_code == 200
    new_secret = rotated.json()["signing_secret"]
    assert new_secret != setup.secret
    assert send_webhook(setup, {"id": "old-secret"}).status_code == 202  # old still valid in grace period
    setup.secret = new_secret
    assert send_webhook(setup, {"id": "new-secret"}).status_code == 202

    # rotate without grace: previous secret immediately invalid
    old = new_secret
    client.post(f"{base}/rotate-secret", json={"grace_period_minutes": 0}, headers=admin.headers)
    setup.secret = old
    assert send_webhook(setup, {"id": "after-hard-rotation"}).status_code == 401
    revealed = client.get(f"{base}/secret", headers=admin.headers).json()["signing_secret"]
    setup.secret = revealed
    assert send_webhook(setup, {"id": "revealed"}).status_code == 202


def test_event_without_routes_is_ignored(client: TestClient, admin, send_webhook) -> None:  # type: ignore[no-untyped-def]
    ep = client.post(
        f"/api/v1/orgs/{admin.org_id}/endpoints", json={"name": "Lonely"}, headers=admin.headers
    ).json()

    class S:
        endpoint = ep
        secret = ep["signing_secret"]

    r = send_webhook(S, {"id": "1"})
    assert r.status_code == 202 and r.json()["status"] == "IGNORED" and r.json()["deliveries"] == 0
