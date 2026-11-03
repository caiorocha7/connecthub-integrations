"""Real queue test: publish through the outbox to Redis and consume with a real Celery worker."""

from __future__ import annotations

import time
import uuid

import httpx
import pytest
import redis
from sqlalchemy import select

from app.core.config import get_settings
from app.models import Delivery
from app.services.outbox import publish_due
from tests.conftest import mock_client


def _redis_available() -> bool:
    try:
        return bool(redis.Redis.from_url(get_settings().redis_url, socket_timeout=1).ping())
    except Exception:
        return False


@pytest.mark.broker
@pytest.mark.skipif(not _redis_available(), reason="Redis indisponível")
def test_outbox_publish_and_celery_consume(
    admin, make_setup, send_webhook, session_factory, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from celery.contrib.testing.worker import start_worker

    import app.worker.tasks as tasks
    from app.worker.celery_app import celery_app

    redis.Redis.from_url(get_settings().redis_url).flushdb()
    received: list[httpx.Request] = []
    monkeypatch.setattr(
        tasks, "_client", lambda: mock_client(lambda r: received.append(r) or httpx.Response(200))
    )

    setup = make_setup(admin)
    event_id = send_webhook(setup, {"id": "via-redis"}).json()["event_id"]
    with session_factory() as db:
        did = db.scalar(select(Delivery.id).where(Delivery.event_id == uuid.UUID(event_id)))

    assert publish_due(session_factory, tasks.celery_publisher) == 1  # real send_task to Redis

    with start_worker(
        celery_app, pool="solo", concurrency=1, perform_ping_check=False, queues=["deliveries"]
    ):
        deadline = time.time() + 20
        status = None
        while time.time() < deadline:
            with session_factory() as db:
                status = db.scalar(select(Delivery.status).where(Delivery.id == did))
            if status == "SUCCEEDED":
                break
            time.sleep(0.2)
    assert status == "SUCCEEDED"
    assert len(received) == 1
