"""Multi-tenant isolation and role-based authorization."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_other_tenant_cannot_access_resources(
    client: TestClient, make_account, make_setup, send_webhook
) -> None:  # type: ignore[no-untyped-def]
    alice = make_account(org="Alice Co")
    bob = make_account(org="Bob Co")
    setup = make_setup(alice)
    assert send_webhook(setup, {"id": "evt-1"}).status_code == 202

    a_base = f"/api/v1/orgs/{alice.org_id}"
    # Bob using Alice's org id -> 404 (existence not revealed)
    for path in ("/endpoints", "/destinations", "/events", "/deliveries", "/dashboard/summary", "/members"):
        assert client.get(a_base + path, headers=bob.headers).status_code == 404, path

    # Bob using his own org id but Alice's resource ids -> 404
    b_base = f"/api/v1/orgs/{bob.org_id}"
    ep_id = setup.endpoint["id"]
    dest_id = setup.destination["id"]
    assert client.get(f"{b_base}/endpoints/{ep_id}", headers=bob.headers).status_code == 404
    assert (
        client.patch(
            f"{b_base}/destinations/{dest_id}", json={"name": "hack"}, headers=bob.headers
        ).status_code
        == 404
    )
    assert client.get(f"{b_base}/endpoints/{ep_id}/secret", headers=bob.headers).status_code == 404
    event_id = client.get(f"{a_base}/events", headers=alice.headers).json()["items"][0]["id"]
    assert client.get(f"{b_base}/events/{event_id}", headers=bob.headers).status_code == 404
    assert client.post(f"{b_base}/events/{event_id}/replay", headers=bob.headers).status_code == 404

    # Bob cannot route his endpoint to Alice's destination
    bob_ep = client.post(f"{b_base}/endpoints", json={"name": "Bob EP"}, headers=bob.headers).json()
    r = client.post(
        f"{b_base}/endpoints/{bob_ep['id']}/routes", json={"destination_id": dest_id}, headers=bob.headers
    )
    assert r.status_code == 404

    # Lists only contain own data
    assert client.get(f"{b_base}/events", headers=bob.headers).json()["total"] == 0
    assert len(client.get(f"{b_base}/destinations", headers=bob.headers).json()) == 0


def test_operator_role_permissions(client: TestClient, make_account, make_setup) -> None:  # type: ignore[no-untyped-def]
    admin = make_account(org="Team")
    operator = make_account(org="Operator Personal")
    base = f"/api/v1/orgs/{admin.org_id}"
    setup = make_setup(admin)

    r = client.post(
        f"{base}/members", json={"email": operator.email, "role": "OPERATOR"}, headers=admin.headers
    )
    assert r.status_code == 201

    # operator can read
    assert client.get(f"{base}/endpoints", headers=operator.headers).status_code == 200
    assert client.get(f"{base}/dashboard/summary", headers=operator.headers).status_code == 200
    # operator cannot change configuration or reveal secrets
    assert (
        client.post(f"{base}/endpoints", json={"name": "x-op"}, headers=operator.headers).status_code == 403
    )
    assert (
        client.post(
            f"{base}/destinations", json={"name": "d", "url": "http://127.0.0.1/x"}, headers=operator.headers
        ).status_code
        == 403
    )
    assert (
        client.get(f"{base}/endpoints/{setup.endpoint['id']}/secret", headers=operator.headers).status_code
        == 403
    )
    assert (
        client.post(f"{base}/members", json={"email": "a@b.com"}, headers=operator.headers).status_code == 403
    )
    assert client.get(f"{base}/audit-logs", headers=operator.headers).status_code == 403


def test_member_management_keeps_last_admin(client: TestClient, make_account) -> None:  # type: ignore[no-untyped-def]
    admin = make_account(org="Solo")
    base = f"/api/v1/orgs/{admin.org_id}"
    members = client.get(f"{base}/members", headers=admin.headers).json()
    assert len(members) == 1
    mid = members[0]["id"]
    assert (
        client.patch(f"{base}/members/{mid}", json={"role": "OPERATOR"}, headers=admin.headers).status_code
        == 409
    )
    assert client.delete(f"{base}/members/{mid}", headers=admin.headers).status_code == 409

    other = make_account(org="Other")
    added = client.post(
        f"{base}/members", json={"email": other.email, "role": "ADMIN"}, headers=admin.headers
    )
    assert added.status_code == 201
    assert (
        client.post(f"{base}/members", json={"email": other.email}, headers=admin.headers).status_code == 409
    )
    assert (
        client.post(f"{base}/members", json={"email": "ghost@example.com"}, headers=admin.headers).status_code
        == 404
    )
    # now demoting the first admin is allowed
    assert (
        client.patch(f"{base}/members/{mid}", json={"role": "OPERATOR"}, headers=admin.headers).status_code
        == 200
    )


def test_create_and_list_organizations(client: TestClient, admin) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/orgs", json={"name": "Segunda Empresa"}, headers=admin.headers)
    assert r.status_code == 201
    assert r.json()["role"] == "ADMIN"
    assert r.json()["slug"].startswith("segunda-empresa")
    orgs = client.get("/api/v1/orgs", headers=admin.headers).json()
    assert {o["name"] for o in orgs} == {"Acme Corp", "Segunda Empresa"}
