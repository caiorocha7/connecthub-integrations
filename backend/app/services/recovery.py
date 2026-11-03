"""Recovery jobs and manual replay."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import exists, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models import (
    AttemptOutcome,
    AttemptTrigger,
    Delivery,
    DeliveryAttempt,
    DeliveryStatus,
    Destination,
    OutboxMessage,
    OutboxStatus,
)
from app.services.common import record_audit, refresh_event_status, utcnow
from app.services.outbox import enqueue_delivery, purge_published

logger = logging.getLogger(__name__)


@dataclass
class RecoveryReport:
    stuck_recovered: int = 0
    stuck_failed: int = 0
    orphans_requeued: int = 0
    outbox_purged: int = 0


def recover(session_factory: sessionmaker[Session], limit: int = 100) -> RecoveryReport:
    """Heal deliveries whose worker died mid-flight and deliveries whose message was lost."""
    settings = get_settings()
    report = RecoveryReport()
    with session_factory() as db:
        now = utcnow()
        # 1) PROCESSING with an expired lock -> worker crashed / was killed.
        stuck = db.scalars(
            select(Delivery)
            .where(Delivery.status == DeliveryStatus.PROCESSING, Delivery.locked_until < now)
            .with_for_update(skip_locked=True)
            .limit(limit)
        ).all()
        for delivery in stuck:
            db.execute(
                update(DeliveryAttempt)
                .where(
                    DeliveryAttempt.delivery_id == delivery.id,
                    DeliveryAttempt.outcome == AttemptOutcome.IN_PROGRESS,
                )
                .values(
                    outcome=AttemptOutcome.RETRYABLE_ERROR,
                    error_type="worker_lost",
                    error_message="worker interrompido antes de concluir a tentativa",
                    finished_at=now,
                )
            )
            delivery.locked_by = None
            delivery.locked_until = None
            if delivery.attempt_count >= delivery.max_attempts:
                delivery.status = DeliveryStatus.FAILED
                delivery.failed_at = now
                delivery.last_error = "worker interrompido e limite de tentativas atingido"
                report.stuck_failed += 1
            else:
                delivery.status = DeliveryStatus.RETRYING
                delivery.next_attempt_at = now
                delivery.next_trigger = AttemptTrigger.RECOVERY
                enqueue_delivery(db, delivery, available_at=now)
                report.stuck_recovered += 1
            refresh_event_status(db, delivery.event_id)

        # 2) Waiting deliveries with no pending outbox message long after they were due
        #    (e.g. broker lost the published message). Re-enqueue; the claim makes it safe.
        grace = now - timedelta(seconds=settings.stuck_delivery_grace_seconds)
        has_pending_message = exists().where(
            OutboxMessage.aggregate_id == Delivery.id,
            OutboxMessage.status == OutboxStatus.PENDING,
        )
        orphans = db.scalars(
            select(Delivery)
            .where(
                Delivery.status.in_([DeliveryStatus.PENDING, DeliveryStatus.RETRYING]),
                func.coalesce(Delivery.next_attempt_at, Delivery.created_at) < grace,
                ~has_pending_message,
            )
            .with_for_update(skip_locked=True)
            .limit(limit)
        ).all()
        for delivery in orphans:
            enqueue_delivery(db, delivery, available_at=now)
            report.orphans_requeued += 1

        report.outbox_purged = purge_published(db)
        db.commit()
    if report.stuck_recovered or report.stuck_failed or report.orphans_requeued:
        logger.warning("recovery executed", extra=report.__dict__)
    return report


class ReplayError(Exception):
    pass


def replay_delivery(
    db: Session, delivery_id: uuid.UUID, organization_id: uuid.UUID, actor_user_id: uuid.UUID
) -> Delivery:
    """Manually re-open a FAILED delivery with a fresh attempt budget. Caller commits."""
    delivery = db.execute(
        select(Delivery)
        .where(Delivery.id == delivery_id, Delivery.organization_id == organization_id)
        .with_for_update()
    ).scalar_one_or_none()
    if delivery is None:
        raise LookupError("delivery not found")
    if delivery.status != DeliveryStatus.FAILED:
        raise ReplayError("apenas entregas com status FAILED podem ser reprocessadas")
    destination = db.get(Destination, delivery.destination_id)
    budget = destination.max_attempts if destination else get_settings().default_max_attempts
    now = utcnow()
    delivery.status = DeliveryStatus.PENDING
    delivery.max_attempts = delivery.attempt_count + budget
    delivery.next_attempt_at = now
    delivery.next_trigger = AttemptTrigger.MANUAL
    delivery.replay_count += 1
    delivery.failed_at = None
    enqueue_delivery(db, delivery, available_at=now)
    record_audit(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action="delivery.replay",
        resource_type="delivery",
        resource_id=delivery.id,
        details={
            "event_id": str(delivery.event_id),
            "previous_attempts": delivery.attempt_count,
            "new_max_attempts": delivery.max_attempts,
        },
    )
    refresh_event_status(db, delivery.event_id)
    return delivery
