"""Outbox relay, crash recovery and manual replay."""

from __future__ import annotations

import uuid
from datetime import timedelta

import httpx
from sqlalchemy import func, select, update

from app.models import AuditLog, Delivery, DeliveryAttempt, OutboxMessage, OutboxStatus
from app.services.common import utcnow
from app.services.delivery import process_delivery
from app.services.outbox import publish_due
from app.services.recovery import recover
from tests.conftest import mock_client


def _delivery(session_factory, event_id: str) -> Delivery:  # type: ignore[no-untyped-def]
    with session_factory() as db:
        return db.scalar(select(Delivery).where(Delivery.event_id == uuid.UUID(event_id)))  # type: ignore[return-value]


def test_event_persisted_but_broker_down_is_published_later(
    admin, make_setup, send_webhook, session_factory
) -> None:  # type: ignore[no-untyped-def]
    """Simulates the API committing the event while the broker is unavailable."""
    setup = make_setup(admin)
    send_webhook(setup, {"id": "a"})
    send_webhook(setup, {"id": "b"})

    def broker_down(message: OutboxMessage) -> None:
        raise ConnectionError("redis unavailable")

    assert publish_due(session_factory, broker_down) == 0
    with session_factory() as db:
        pending = db.scalars(select(OutboxMessage).where(OutboxMessage.status == OutboxStatus.PENDING)).all()
        assert len(pending) == 2
        assert any(m.last_error and "redis unavailable" in m.last_error for m in pending)

    published: list[str] = []
    assert publish_due(session_factory, lambda m: published.append(m.payload["delivery_id"])) == 2
    assert publish_due(session_factory, lambda m: published.append("dup")) == 0  # nothing re-published
    assert len(published) == 2
    with session_factory() as db:
        assert db.scalar(select(func.count()).where(OutboxMessage.status == OutboxStatus.PENDING)) == 0


def test_relay_respects_available_at(admin, make_setup, send_webhook, session_factory) -> None:  # type: ignore[no-untyped-def]
    setup = make_setup(admin)
    send_webhook(setup, {"id": "future"})
    with session_factory() as db:
        db.execute(update(OutboxMessage).values(available_at=utcnow() + timedelta(minutes=5)))
        db.commit()
    assert publish_due(session_factory, lambda m: None) == 0
    assert publish_due(session_factory, lambda m: None, now=utcnow() + timedelta(minutes=6)) == 1


def test_recovery_of_delivery_stuck_in_processing(admin, make_setup, send_webhook, session_factory) -> None:  # type: ignore[no-untyped-def]
    setup = make_setup(admin, max_attempts=3)
    d = _delivery(session_factory, send_webhook(setup, {"id": "stuck"}).json()["event_id"])
    now = utcnow()
    with session_factory() as db:  # simulate a worker that claimed the delivery and died
        db.execute(
            update(Delivery)
            .where(Delivery.id == d.id)
            .values(
                status="PROCESSING",
                attempt_count=1,
                locked_by="dead:1",
                locked_until=now - timedelta(seconds=1),
            )
        )
        db.add(
            DeliveryAttempt(
                organization_id=d.organization_id,
                delivery_id=d.id,
                attempt_number=1,
                trigger="AUTO",
                outcome="IN_PROGRESS",
                request_url="http://127.0.0.1:9/hook",
                request_method="POST",
                started_at=now - timedelta(minutes=2),
            )
        )
        db.execute(update(OutboxMessage).values(status=OutboxStatus.PUBLISHED))
        db.commit()

    report = recover(session_factory)
    assert report.stuck_recovered == 1
    with session_factory() as db:
        delivery = db.get(Delivery, d.id)
        assert delivery.status == "RETRYING" and delivery.locked_by is None
        assert delivery.next_trigger == "RECOVERY"
        att = db.scalar(select(DeliveryAttempt).where(DeliveryAttempt.delivery_id == d.id))
        assert att.outcome == "RETRYABLE_ERROR" and att.error_type == "worker_lost"
        assert (
            db.scalar(
                select(func.count()).where(
                    OutboxMessage.aggregate_id == d.id, OutboxMessage.status == OutboxStatus.PENDING
                )
            )
            == 1
        )

    result = process_delivery(
        d.id,
        session_factory=session_factory,
        client=mock_client(lambda r: httpx.Response(200)),
        worker_id="w2",
    )
    assert result == "succeeded"
    with session_factory() as db:
        attempts = db.scalars(
            select(DeliveryAttempt)
            .where(DeliveryAttempt.delivery_id == d.id)
            .order_by(DeliveryAttempt.attempt_number)
        ).all()
        assert [(a.attempt_number, a.trigger) for a in attempts] == [(1, "AUTO"), (2, "RECOVERY")]


def test_recovery_requeues_orphan_delivery(admin, make_setup, send_webhook, session_factory) -> None:  # type: ignore[no-untyped-def]
    """Message was published but lost by the broker: delivery stays PENDING without outbox."""
    setup = make_setup(admin)
    d = _delivery(session_factory, send_webhook(setup, {"id": "orphan"}).json()["event_id"])
    with session_factory() as db:
        db.execute(update(OutboxMessage).values(status=OutboxStatus.PUBLISHED, published_at=utcnow()))
        db.execute(update(Delivery).values(next_attempt_at=utcnow() - timedelta(minutes=10)))
        db.commit()
    assert recover(session_factory).orphans_requeued == 1
    assert recover(session_factory).orphans_requeued == 0  # pending message exists now
    with session_factory() as db:
        assert (
            db.scalar(
                select(func.count()).where(
                    OutboxMessage.aggregate_id == d.id, OutboxMessage.status == "PENDING"
                )
            )
            == 1
        )


def test_manual_replay_of_failed_delivery(
    client, admin, make_setup, send_webhook, session_factory, captured_dispatch
) -> None:  # type: ignore[no-untyped-def]
    setup = make_setup(admin, max_attempts=1)
    event_id = send_webhook(setup, {"id": "replay-me"}).json()["event_id"]
    d = _delivery(session_factory, event_id)
    fail = mock_client(lambda r: httpx.Response(503))
    assert process_delivery(d.id, session_factory=session_factory, client=fail, worker_id="w") == "failed"

    base = f"/api/v1/orgs/{admin.org_id}"
    r = client.post(f"{base}/deliveries/{d.id}/replay", headers=admin.headers)
    assert r.status_code == 200 and r.json()["replayed"] == 1
    assert (
        client.post(f"{base}/deliveries/{d.id}/replay", headers=admin.headers).status_code == 409
    )  # not FAILED now
    assert len(captured_dispatch) == 2  # ingest + replay

    with session_factory() as db:
        delivery = db.get(Delivery, d.id)
        assert delivery.status == "PENDING" and delivery.replay_count == 1 and delivery.max_attempts == 2
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "delivery.replay"))
        assert audit is not None and audit.resource_id == str(d.id)

    ok = mock_client(lambda r: httpx.Response(200))
    assert process_delivery(d.id, session_factory=session_factory, client=ok, worker_id="w") == "succeeded"
    detail = client.get(f"{base}/deliveries/{d.id}", headers=admin.headers).json()
    assert [a["trigger"] for a in detail["attempts"]] == ["AUTO", "MANUAL"]
    assert [a["outcome"] for a in detail["attempts"]] == ["RETRYABLE_ERROR", "SUCCESS"]
    assert client.get(f"{base}/events/{event_id}", headers=admin.headers).json()["status"] == "SUCCEEDED"


def test_event_level_replay_and_operator_can_replay(
    client, make_account, make_setup, send_webhook, session_factory
) -> None:  # type: ignore[no-untyped-def]
    admin = make_account(org="Ops")
    operator = make_account(org="Op Personal")
    base = f"/api/v1/orgs/{admin.org_id}"
    client.post(f"{base}/members", json={"email": operator.email, "role": "OPERATOR"}, headers=admin.headers)
    setup = make_setup(admin, max_attempts=1)
    event_id = send_webhook(setup, {"id": "ev-replay"}).json()["event_id"]
    assert client.post(f"{base}/events/{event_id}/replay", headers=operator.headers).status_code == 409
    d = _delivery(session_factory, event_id)
    process_delivery(
        d.id,
        session_factory=session_factory,
        client=mock_client(lambda r: httpx.Response(500)),
        worker_id="w",
    )
    r = client.post(f"{base}/events/{event_id}/replay", headers=operator.headers)
    assert r.status_code == 200 and r.json()["delivery_ids"] == [str(d.id)]
    logs = client.get(f"{base}/audit-logs?action=delivery.replay", headers=admin.headers).json()
    assert logs["total"] == 1 and logs["items"][0]["actor_email"] == operator.email
