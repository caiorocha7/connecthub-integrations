"""Explicit state machines and enumerations used across the domain."""

from __future__ import annotations

import enum


class Role(enum.StrEnum):
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"


class EventStatus(enum.StrEnum):
    """Aggregate state of a received event (derived from its deliveries)."""

    RECEIVED = "RECEIVED"  # persisted, deliveries not yet attempted
    PROCESSING = "PROCESSING"  # at least one delivery in flight
    RETRYING = "RETRYING"  # at least one delivery waiting for a retry
    SUCCEEDED = "SUCCEEDED"  # every delivery succeeded
    FAILED = "FAILED"  # every delivery finished and at least one failed
    IGNORED = "IGNORED"  # no active route existed when the event arrived


class DeliveryStatus(enum.StrEnum):
    """State of one logical delivery (event x destination)."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    RETRYING = "RETRYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


ACTIVE_DELIVERY_STATUSES = (
    DeliveryStatus.PENDING,
    DeliveryStatus.PROCESSING,
    DeliveryStatus.RETRYING,
)


class AttemptOutcome(enum.StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    SUCCESS = "SUCCESS"
    RETRYABLE_ERROR = "RETRYABLE_ERROR"
    PERMANENT_ERROR = "PERMANENT_ERROR"


class AttemptTrigger(enum.StrEnum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"
    RECOVERY = "RECOVERY"


class OutboxStatus(enum.StrEnum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"


class HttpMethod(enum.StrEnum):
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
