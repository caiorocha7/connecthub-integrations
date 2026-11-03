"""Received events, logical deliveries, delivery attempts, outbox and audit log."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey
from app.models.enums import (
    AttemptOutcome,
    AttemptTrigger,
    DeliveryStatus,
    EventStatus,
    OutboxStatus,
)


class Event(UUIDPrimaryKey, Timestamps, Base):
    """A webhook received on an endpoint. Unique per (organization, endpoint, external id)."""

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("organization_id", "endpoint_id", "external_event_id", name="uq_event_idempotency"),
        Index("ix_events_org_received", "organization_id", "received_at"),
        Index("ix_events_org_status", "organization_id", "status"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("endpoints.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_id_source: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[EventStatus] = mapped_column(
        Enum(EventStatus, native_enum=False, length=20, name="event_status"),
        default=EventStatus.RECEIVED,
        nullable=False,
    )
    payload: Mapped[Any] = mapped_column(JSONB, nullable=False)
    payload_size: Mapped[int] = mapped_column(Integer, nullable=False)
    headers: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict, nullable=False)
    source_ip: Mapped[str | None] = mapped_column(String(64))
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_duplicate_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    endpoint = relationship("Endpoint")
    deliveries: Mapped[list[Delivery]] = relationship(
        back_populates="event", cascade="all, delete-orphan", order_by="Delivery.created_at"
    )


class Delivery(UUIDPrimaryKey, Timestamps, Base):
    """One logical delivery of an event to a destination (never duplicated)."""

    __tablename__ = "deliveries"
    __table_args__ = (
        UniqueConstraint("event_id", "destination_id", name="uq_delivery_event_destination"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_positive"),
        Index("ix_deliveries_org_status", "organization_id", "status"),
        Index("ix_deliveries_org_created", "organization_id", "created_at"),
        Index(
            "ix_deliveries_stuck",
            "status",
            "locked_until",
            postgresql_where=text("status = 'PROCESSING'"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    destination_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("destinations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    route_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("routes.id", ondelete="SET NULL"))
    transform_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transform_rules.id", ondelete="SET NULL")
    )
    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, native_enum=False, length=20, name="delivery_status"),
        default=DeliveryStatus.PENDING,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_trigger: Mapped[AttemptTrigger] = mapped_column(
        Enum(AttemptTrigger, native_enum=False, length=20, name="attempt_trigger"),
        default=AttemptTrigger.AUTO,
        nullable=False,
    )
    locked_by: Mapped[str | None] = mapped_column(String(120))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    transformed_payload: Mapped[Any | None] = mapped_column(JSONB)
    replay_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    event: Mapped[Event] = relationship(back_populates="deliveries")
    destination = relationship("Destination")
    attempts: Mapped[list[DeliveryAttempt]] = relationship(
        back_populates="delivery",
        cascade="all, delete-orphan",
        order_by="DeliveryAttempt.attempt_number",
    )


class DeliveryAttempt(UUIDPrimaryKey, Base):
    """One HTTP execution of a delivery. (delivery, attempt_number) is unique."""

    __tablename__ = "delivery_attempts"
    __table_args__ = (UniqueConstraint("delivery_id", "attempt_number", name="uq_attempt_delivery_number"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    delivery_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("deliveries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger: Mapped[AttemptTrigger] = mapped_column(
        Enum(AttemptTrigger, native_enum=False, length=20, name="attempt_trigger"),
        nullable=False,
    )
    outcome: Mapped[AttemptOutcome] = mapped_column(
        Enum(AttemptOutcome, native_enum=False, length=20, name="attempt_outcome"),
        default=AttemptOutcome.IN_PROGRESS,
        nullable=False,
    )
    worker_id: Mapped[str | None] = mapped_column(String(120))
    request_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    request_method: Mapped[str] = mapped_column(String(10), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    error_type: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(Text)
    response_excerpt: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    delivery: Mapped[Delivery] = relationship(back_populates="attempts")


class OutboxMessage(UUIDPrimaryKey, Base):
    """Transactional outbox: written in the same transaction as the domain change."""

    __tablename__ = "outbox_messages"
    __table_args__ = (
        Index(
            "ix_outbox_pending_due",
            "available_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    topic: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[OutboxStatus] = mapped_column(
        Enum(OutboxStatus, native_enum=False, length=20, name="outbox_status"),
        default=OutboxStatus.PENDING,
        nullable=False,
    )
    publish_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(UUIDPrimaryKey, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_org_created", "organization_id", "created_at"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    actor = relationship("User")
