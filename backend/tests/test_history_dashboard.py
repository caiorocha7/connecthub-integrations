"""History listing, filters, pagination, masking and dashboard metrics."""

from __future__ import annotations

import uuid
from datetime import timedelta

import httpx
from sqlalchemy import select

from app.models import Delivery
from app.services.common import utcnow
from app.services.delivery import process_delivery
from tests.conftest import mock_client


def _process(session_factory, event_id: str, status: int) -> None:  # type: ignore[no-untyped-def]
    with session_factory() as db:
        did = db.scalar(select(Delivery.id).where(Delivery.event_id == uuid.UUID(event_id)))
    process_delivery(
        did,
        session_factory=session_factory,
        client=mock_client(lambda r: httpx.Response(status)),
        worker_id="w",
    )


def test_event_and_delivery_filters(client, admin, make_setup, send_webhook, session_factory) -> None:  # type: ignore[no-untyped-def]
    a = make_setup(admin, max_attempts=1)
    b = make_setup(admin, max_attempts=1)
    ok_ids = [send_webhook(a, {"id": f"ok-{i}"}).json()["event_id"] for i in range(3)]
    fail_id = send_webhook(b, {"id": "fail-1"}).json()["event_id"]
    for eid in ok_ids:
        _process(session_factory, eid, 200)
    _process(session_factory, fail_id, 500)

    base = f"/api/v1/orgs/{admin.org_id}"
    h = admin.headers
    all_events = client.get(f"{base}/events", headers=h).json()
    assert all_events["total"] == 4

    failed = client.get(f"{base}/events", params={"status": "FAILED"}, headers=h).json()
    assert [e["id"] for e in failed["items"]] == [fail_id]
    by_endpoint = client.get(f"{base}/events", params={"endpoint_id": a.endpoint["id"]}, headers=h).json()
    assert by_endpoint["total"] == 3
    by_dest = client.get(f"{base}/events", params={"destination_id": b.destination["id"]}, headers=h).json()
    assert by_dest["total"] == 1
    search = client.get(f"{base}/events", params={"search": "ok-1"}, headers=h).json()
    assert search["total"] == 1

    future = (utcnow() + timedelta(hours=1)).isoformat()
    assert client.get(f"{base}/events", params={"date_from": future}, headers=h).json()["total"] == 0
    past = (utcnow() - timedelta(hours=1)).isoformat()
    assert (
        client.get(f"{base}/events", params={"date_from": past, "date_to": future}, headers=h).json()["total"]
        == 4
    )

    page = client.get(f"{base}/events", params={"page": 2, "page_size": 3}, headers=h).json()
    assert page["pages"] == 2 and len(page["items"]) == 1

    deliveries = client.get(f"{base}/deliveries", params={"status": "SUCCEEDED"}, headers=h).json()
    assert deliveries["total"] == 3
    assert (
        client.get(f"{base}/deliveries", params={"destination_id": b.destination["id"]}, headers=h).json()[
            "total"
        ]
        == 1
    )
    assert client.get(f"{base}/deliveries", params={"status": "INVALID"}, headers=h).status_code == 422


def test_event_detail_masks_sensitive_fields(client, admin, make_setup, send_webhook) -> None:  # type: ignore[no-untyped-def]
    setup = make_setup(admin)
    eid = send_webhook(
        setup, {"id": "m1", "customer": {"name": "Ana", "cpf": "123"}, "password": "x"}
    ).json()["event_id"]
    detail = client.get(f"/api/v1/orgs/{admin.org_id}/events/{eid}", headers=admin.headers).json()
    assert detail["payload"] == {"id": "m1", "customer": {"name": "Ana", "cpf": "***"}, "password": "***"}
    assert detail["deliveries"][0]["status"] == "PENDING"


def test_dashboard_summary(client, admin, make_setup, send_webhook, session_factory) -> None:  # type: ignore[no-untyped-def]
    setup = make_setup(admin, max_attempts=1)
    ids = [send_webhook(setup, {"id": f"d{i}"}).json()["event_id"] for i in range(4)]
    send_webhook(setup, {"id": "d0"})  # duplicate
    _process(session_factory, ids[0], 200)
    _process(session_factory, ids[1], 200)
    _process(session_factory, ids[2], 500)

    s = client.get(f"/api/v1/orgs/{admin.org_id}/dashboard/summary", headers=admin.headers).json()
    assert s["events_received"] == 4
    assert s["duplicates_blocked"] == 1
    assert s["deliveries_succeeded"] == 2
    assert s["deliveries_failed"] == 1
    assert s["deliveries_pending"] == 1
    assert s["success_rate"] == 66.7
    assert sum(b["received"] for b in s["timeline"]) == 4
    assert sum(b["succeeded"] for b in s["timeline"]) == 2
    assert s["destinations"][0]["failed"] == 1
    assert s["recent_failures"][0]["status"] == "FAILED"
