"""Transactional outbox.

Domain changes and the "please deliver" message are written in the *same* database transaction.
A relay (periodic Celery beat task + best-effort immediate dispatch from the API) publishes due
messages to the broker. If the broker is unavailable, messages stay PENDING and are retried, so an
event can never be persisted without eventually being enqueued.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Delivery, OutboxMessage, OutboxStatus
from app.services.common import utcnow

logger = logging.getLogger(__name__)

TOPIC_DELIVER = "delivery.dispatch"

Publisher = Callable[[OutboxMessage], None]


def enqueue_delivery(db: Session, delivery: Delivery, available_at: datetime | None = None) -> OutboxMessage:
    message = OutboxMessage(
        id=uuid.uuid4(),
        organization_id=delivery.organization_id,
        topic=TOPIC_DELIVER,
        aggregate_id=delivery.id,
        payload={"delivery_id": str(delivery.id)},
        available_at=available_at or utcnow(),
    )
    db.add(message)
    return message


def publish_due(
    session_factory: sessionmaker[Session],
    publisher: Publisher,
    *,
    ids: Sequence[uuid.UUID] | None = None,
    limit: int = 200,
    now: datetime | None = None,
) -> int:
    """Publish due PENDING messages. Rows are locked with SKIP LOCKED so concurrent relays
    never publish the same message twice in parallel. Returns the number published."""
    now = now or utcnow()
    published = 0
    with session_factory() as db:
        stmt = (
            select(OutboxMessage)
            .where(OutboxMessage.status == OutboxStatus.PENDING, OutboxMessage.available_at <= now)
            .order_by(OutboxMessage.available_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        if ids is not None:
            if not ids:
                return 0
            stmt = stmt.where(OutboxMessage.id.in_(list(ids)))
        messages = db.scalars(stmt).all()
        for message in messages:
            message.publish_attempts += 1
            try:
                publisher(message)
            except Exception as exc:  # broker down: keep PENDING, retry later
                message.last_error = f"{type(exc).__name__}: {exc}"[:500]
                logger.warning(
                    "outbox publish failed",
                    extra={"outbox_id": str(message.id), "error": message.last_error},
                )
                break
            message.status = OutboxStatus.PUBLISHED
            message.published_at = utcnow()
            message.last_error = None
            published += 1
        db.commit()
    if published:
        logger.info("outbox messages published", extra={"count": published})
    return published


def purge_published(db: Session, older_than: timedelta = timedelta(days=7)) -> int:
    result = db.execute(
        delete(OutboxMessage).where(
            OutboxMessage.status == OutboxStatus.PUBLISHED,
            OutboxMessage.published_at < utcnow() - older_than,
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)
