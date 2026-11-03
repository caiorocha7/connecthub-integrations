"""Test fixtures. Tests run against a real PostgreSQL database (``connecthub_test``)."""

from __future__ import annotations

import os

os.environ.setdefault(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://connecthub:connecthub_dev_password@localhost:5442/connecthub_test",
)
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ.setdefault("REDIS_URL", "redis://localhost:6392/15")
os.environ["SSRF_ALLOWED_HOSTS"] = "127.0.0.1,localhost"
os.environ["LOG_JSON"] = "false"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["ENVIRONMENT"] = "test"

import json
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from alembic import command


def _ensure_database() -> None:
    url = make_url(os.environ["DATABASE_URL"])
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database})
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()


_ensure_database()
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cfg = Config(os.path.join(_backend_dir, "alembic.ini"))
_cfg.set_main_option("script_location", os.path.join(_backend_dir, "alembic"))
command.upgrade(_cfg, "head")

from app.core.security import build_signature_header  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402

TABLES = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))


@pytest.fixture(autouse=True)
def clean_db() -> Iterator[None]:
    yield
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))


@pytest.fixture(autouse=True)
def captured_dispatch(monkeypatch: pytest.MonkeyPatch) -> list[list[uuid.UUID]]:
    """Replace the broker dispatch used by the API with an in-memory recorder."""
    calls: list[list[uuid.UUID]] = []
    import app.worker.tasks as tasks

    monkeypatch.setattr(tasks, "dispatch_now", lambda ids: calls.append(list(ids)))
    return calls


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def session_factory():  # type: ignore[no-untyped-def]
    return SessionLocal


@dataclass
class Account:
    email: str
    password: str
    token: str
    refresh: str
    org_id: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


@pytest.fixture
def make_account(client: TestClient) -> Callable[..., Account]:
    def _make(email: str | None = None, org: str = "Acme Corp", password: str = "Senha@123") -> Account:
        email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
        r = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "full_name": "Test User", "organization_name": org},
        )
        assert r.status_code == 201, r.text
        tokens = r.json()
        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
        org_id = me.json()["memberships"][0]["organization_id"]
        return Account(email, password, tokens["access_token"], tokens["refresh_token"], org_id)

    return _make


@pytest.fixture
def admin(make_account: Callable[..., Account]) -> Account:
    return make_account()


@dataclass
class Setup:
    account: Account
    endpoint: dict[str, Any]
    destination: dict[str, Any]
    secret: str


@pytest.fixture
def make_setup(client: TestClient) -> Callable[..., Setup]:
    def _make(
        account: Account,
        url: str = "http://127.0.0.1:9/hook",
        max_attempts: int = 3,
        transform_rule_id: str | None = None,
    ) -> Setup:
        base = f"/api/v1/orgs/{account.org_id}"
        ep = client.post(
            f"{base}/endpoints", json={"name": f"Orders {uuid.uuid4().hex[:4]}"}, headers=account.headers
        )
        assert ep.status_code == 201, ep.text
        dest = client.post(
            f"{base}/destinations",
            json={
                "name": f"ERP {uuid.uuid4().hex[:4]}",
                "url": url,
                "max_attempts": max_attempts,
                "timeout_seconds": 2,
            },
            headers=account.headers,
        )
        assert dest.status_code == 201, dest.text
        route = client.post(
            f"{base}/endpoints/{ep.json()['id']}/routes",
            json={"destination_id": dest.json()["id"], "transform_rule_id": transform_rule_id},
            headers=account.headers,
        )
        assert route.status_code == 201, route.text
        return Setup(account, ep.json(), dest.json(), ep.json()["signing_secret"])

    return _make


def signed_headers(
    secret: str, body: bytes, event_id: str | None = None, ts: int | None = None
) -> dict[str, str]:
    timestamp = str(ts if ts is not None else int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "X-ConnectHub-Timestamp": timestamp,
        "X-ConnectHub-Signature": build_signature_header(secret, timestamp, body),
    }
    if event_id:
        headers["X-ConnectHub-Event-Id"] = event_id
    return headers


@pytest.fixture
def send_webhook(client: TestClient) -> Callable[..., httpx.Response]:
    def _send(setup: Setup, payload: Any, event_id: str | None = None) -> httpx.Response:
        body = json.dumps(payload).encode()
        return client.post(
            f"/api/v1/ingest/{setup.endpoint['public_id']}",
            content=body,
            headers=signed_headers(setup.secret, body, event_id),
        )

    return _send


def mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))
