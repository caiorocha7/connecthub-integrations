"""Inbound endpoints, outbound destinations, routes and transformation rules."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey
from app.models.enums import HttpMethod


class Endpoint(UUIDPrimaryKey, Timestamps, Base):
    """An inbound webhook endpoint with its own public URL and signing secret."""

    __tablename__ = "endpoints"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_endpoint_org_name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    previous_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    previous_secret_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    secret_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_id_path: Mapped[str] = mapped_column(String(200), default="id", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    routes: Mapped[list[Route]] = relationship(back_populates="endpoint", cascade="all, delete-orphan")


class Destination(UUIDPrimaryKey, Timestamps, Base):
    """An outbound HTTP target."""

    __tablename__ = "destinations"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_destination_org_name"),
        CheckConstraint("timeout_seconds BETWEEN 1 AND 60", name="timeout_range"),
        CheckConstraint("max_attempts BETWEEN 1 AND 20", name="max_attempts_range"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    method: Mapped[HttpMethod] = mapped_column(
        Enum(HttpMethod, native_enum=False, length=10, name="http_method"),
        default=HttpMethod.POST,
        nullable=False,
    )
    headers: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    signing_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    routes: Mapped[list[Route]] = relationship(back_populates="destination")


class TransformRule(UUIDPrimaryKey, Timestamps, Base):
    """Declarative JSON mapping (no code execution)."""

    __tablename__ = "transform_rules"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_transform_org_name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    include_unmapped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mappings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    sample_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Route(UUIDPrimaryKey, Timestamps, Base):
    """Association endpoint -> destination, optionally with a transformation rule."""

    __tablename__ = "routes"
    __table_args__ = (
        UniqueConstraint("endpoint_id", "destination_id", name="uq_route_endpoint_destination"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("endpoints.id", ondelete="CASCADE"), nullable=False, index=True
    )
    destination_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("destinations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transform_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transform_rules.id", ondelete="SET NULL"), index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    endpoint: Mapped[Endpoint] = relationship(back_populates="routes")
    destination: Mapped[Destination] = relationship(back_populates="routes")
    transform_rule: Mapped[TransformRule | None] = relationship()
