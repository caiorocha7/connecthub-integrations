"""Small shared helpers: clock, audit log and event status aggregation."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, Delivery, DeliveryStatus, Event, EventStatus


def utcnow() -> datetime:
    return datetime.now(UTC)


def record_audit(
    db: Session,
    *,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        details=details or {},
    )
    db.add(entry)
    return entry


def aggregate_event_status(statuses: Iterable[DeliveryStatus]) -> EventStatus:
    values = list(statuses)
    if not values:
        return EventStatus.IGNORED
    if all(s == DeliveryStatus.SUCCEEDED for s in values):
        return EventStatus.SUCCEEDED
    if any(s == DeliveryStatus.PROCESSING for s in values):
        return EventStatus.PROCESSING
    if any(s == DeliveryStatus.RETRYING for s in values):
        return EventStatus.RETRYING
    if any(s == DeliveryStatus.PENDING for s in values):
        if all(s == DeliveryStatus.PENDING for s in values):
            return EventStatus.RECEIVED
        return EventStatus.PROCESSING
    return EventStatus.FAILED


def refresh_event_status(db: Session, event_id: uuid.UUID) -> EventStatus:
    """Recompute the aggregate event status.

    The event row is locked (``FOR UPDATE``) so concurrent deliveries of the same event
    serialize here and the last writer always sees every committed delivery state.
    """
    db.flush()  # sessions use autoflush=False: make pending delivery changes visible
    event = db.execute(select(Event).where(Event.id == event_id).with_for_update()).scalar_one()
    statuses = db.scalars(select(Delivery.status).where(Delivery.event_id == event_id)).all()
    event.status = aggregate_event_status(statuses)
    return event.status
