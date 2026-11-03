from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import app


@pytest.fixture
def client() -> TestClient:
    c = TestClient(app)
    c.post("/control/reset")
    return c


def _hook(client: TestClient, event_id: str = "e1", key: str = "d1") -> int:
    r = client.post(
        "/hooks/erp",
        json={"id": event_id},
        headers={"X-ConnectHub-Event-Id": event_id, "Idempotency-Key": key},
    )
    return r.status_code


def test_normal_mode_records_requests(client: TestClient) -> None:
    assert _hook(client) == 200
    data = client.get("/requests").json()
    assert data["total_received"] == 1 and data["succeeded"] == 1
    assert data["items"][0]["body"] == {"id": "e1"}
    assert data["items"][0]["headers"]["idempotency-key"] == "d1"


def test_error_and_rate_limit_modes(client: TestClient) -> None:
    client.put("/control", json={"mode": "error", "status_code": 503})
    assert _hook(client) == 503
    client.put("/control", json={"mode": "rate_limit", "retry_after": 7})
    r = client.post("/hooks/erp", json={})
    assert r.status_code == 429 and r.headers["retry-after"] == "7"
    client.put("/control", json={"mode": "normal"})
    assert _hook(client) == 200


def test_fail_next_returns_to_normal(client: TestClient) -> None:
    client.put("/control", json={"mode": "error", "fail_next": 2})
    assert [_hook(client), _hook(client), _hook(client)] == [500, 500, 200]
    assert client.get("/control").json()["mode"] == "normal"


def test_timeout_mode_delays(client: TestClient) -> None:
    client.put("/control", json={"mode": "timeout", "delay_seconds": 0.2})
    assert _hook(client) == 200
    assert client.get("/requests").json()["items"][0]["response_status"] is None


def test_filter_and_unique_deliveries(client: TestClient) -> None:
    _hook(client, "a", "d1")
    _hook(client, "a", "d1")
    _hook(client, "b", "d2")
    data = client.get("/requests", params={"event_id": "a"}).json()
    assert data["matched"] == 2 and data["unique_successful_deliveries"] == 1
    client.delete("/requests")
    assert client.get("/requests").json()["total_received"] == 0
