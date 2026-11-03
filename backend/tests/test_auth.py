from __future__ import annotations

from fastapi.testclient import TestClient


def test_register_login_me_and_logout(client: TestClient) -> None:
    r = client.post(
        "/api/v1/auth/register",
        json={
            "email": "Ana@Example.com",
            "password": "Segura123",
            "full_name": "Ana Souza",
            "organization_name": "Loja Ana",
        },
    )
    assert r.status_code == 201
    tokens = r.json()
    assert tokens["token_type"] == "bearer" and tokens["expires_in"] > 0

    login = client.post("/api/v1/auth/login", json={"email": "ana@example.com", "password": "Segura123"})
    assert login.status_code == 200
    access = login.json()["access_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "ana@example.com"
    assert body["memberships"][0]["role"] == "ADMIN"
    assert body["memberships"][0]["organization_name"] == "Loja Ana"
    assert "password_hash" not in body

    refresh = login.json()["refresh_token"]
    assert client.post("/api/v1/auth/logout", json={"refresh_token": refresh}).status_code == 204
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": refresh}).status_code == 401


def test_register_rejects_duplicate_and_weak_password(client: TestClient) -> None:
    payload = {"email": "dup@example.com", "password": "Segura123", "full_name": "Dup User"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    assert client.post("/api/v1/auth/register", json=payload).status_code == 409
    weak = client.post(
        "/api/v1/auth/register", json={**payload, "email": "w@example.com", "password": "abcdefgh"}
    )
    assert weak.status_code == 422
    assert weak.json()["errors"][0]["field"] == "password"


def test_login_with_wrong_credentials(client: TestClient, admin) -> None:  # type: ignore[no-untyped-def]
    bad = client.post("/api/v1/auth/login", json={"email": admin.email, "password": "errada123"})
    assert bad.status_code == 401
    unknown = client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "errada123"})
    assert unknown.status_code == 401
    assert bad.json()["detail"] == unknown.json()["detail"]  # no user enumeration


def test_refresh_rotation_and_reuse_detection(client: TestClient, admin) -> None:  # type: ignore[no-untyped-def]
    first = client.post("/api/v1/auth/refresh", json={"refresh_token": admin.refresh})
    assert first.status_code == 200
    new_refresh = first.json()["refresh_token"]
    assert new_refresh != admin.refresh
    # reusing the rotated token revokes the whole family
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": admin.refresh}).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh}).status_code == 401


def test_private_routes_require_valid_token(client: TestClient, admin) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid.token.here"}).status_code
        == 401
    )
    assert client.get(f"/api/v1/orgs/{admin.org_id}/endpoints").status_code == 401


def test_change_password_revokes_sessions(client: TestClient, admin) -> None:  # type: ignore[no-untyped-def]
    r = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": admin.password, "new_password": "NovaSenha456"},
        headers=admin.headers,
    )
    assert r.status_code == 204
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": admin.refresh}).status_code == 401
    assert (
        client.post("/api/v1/auth/login", json={"email": admin.email, "password": "NovaSenha456"}).status_code
        == 200
    )
