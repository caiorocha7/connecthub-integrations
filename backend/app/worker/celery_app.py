"""Celery application: Redis as broker, PostgreSQL as the source of truth for state."""

from __future__ import annotations

from celery import Celery
from celery.signals import after_setup_logger, worker_process_init

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()

celery_app = Celery("connecthub", broker=settings.redis_url, include=["app.worker.tasks"])
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_backend=None,
    task_ignore_result=True,
    timezone="UTC",
    enable_utc=True,
    # at-least-once: ack only after the task finishes; re-deliver if the worker dies
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 3600},
    task_default_queue="deliveries",
    task_routes={
        "connecthub.deliver": {"queue": "deliveries"},
        "connecthub.relay_outbox": {"queue": "maintenance"},
        "connecthub.recover": {"queue": "maintenance"},
    },
    beat_schedule={
        "relay-outbox": {
            "task": "connecthub.relay_outbox",
            "schedule": settings.outbox_relay_interval_seconds,
            "options": {"expires": max(settings.outbox_relay_interval_seconds * 2, 2)},
        },
        "recover-stuck-deliveries": {
            "task": "connecthub.recover",
            "schedule": 30.0,
            "options": {"expires": 60},
        },
    },
    worker_hijack_root_logger=False,
)


@after_setup_logger.connect
def _setup_logging(**_: object) -> None:
    configure_logging(settings.log_level, settings.log_json)


@worker_process_init.connect
def _reset_db_pool(**_: object) -> None:
    # never share pooled connections across forked worker processes
    from app.db.session import engine

    engine.dispose(close=False)
