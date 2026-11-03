"""Celery tasks. Each task is safe to run more than once (claim + idempotent state machine)."""

from __future__ import annotations

import logging
import os
import socket
import uuid
from functools import lru_cache

import httpx

from app.db.session import SessionLocal
from app.models import OutboxMessage
from app.services.delivery import build_http_client, process_delivery
from app.services.outbox import TOPIC_DELIVER, publish_due
from app.services.recovery import recover
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

TASK_DELIVER = "connecthub.deliver"


@lru_cache
def _client() -> httpx.Client:
    return build_http_client()


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def celery_publisher(message: OutboxMessage) -> None:
    if message.topic != TOPIC_DELIVER:
        raise ValueError(f"unknown outbox topic {message.topic}")
    celery_app.send_task(
        TASK_DELIVER,
        args=[message.payload["delivery_id"]],
        queue="deliveries",
        retry=True,
        retry_policy={"max_retries": 2, "interval_start": 0, "interval_step": 0.5},
    )


@celery_app.task(name=TASK_DELIVER, acks_late=True)
def deliver(delivery_id: str) -> str:
    return process_delivery(
        uuid.UUID(delivery_id),
        session_factory=SessionLocal,
        client=_client(),
        worker_id=_worker_id(),
    )


@celery_app.task(name="connecthub.relay_outbox")
def relay_outbox() -> int:
    return publish_due(SessionLocal, celery_publisher)


@celery_app.task(name="connecthub.recover")
def recover_deliveries() -> dict[str, int]:
    return recover(SessionLocal).__dict__


def dispatch_now(outbox_ids: list[uuid.UUID]) -> None:
    """Best-effort immediate publish from the API (the relay covers any failure)."""
    try:
        publish_due(SessionLocal, celery_publisher, ids=outbox_ids)
    except Exception:  # pragma: no cover - relay will pick it up
        logger.exception("immediate dispatch failed; outbox relay will retry")
