from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.enums import AttemptOutcome, AttemptTrigger, DeliveryStatus, EventStatus
from app.schemas.common import ORMModel


class IngestResponse(BaseModel):
    event_id: uuid.UUID
    external_event_id: str
    status: str
    duplicate: bool
    deliveries: int


class AttemptOut(ORMModel):
    id: uuid.UUID
    attempt_number: int
    trigger: AttemptTrigger
    outcome: AttemptOutcome
    request_url: str
    request_method: str
    status_code: int | None
    error_type: str | None
    error_message: str | None
    response_excerpt: str | None
    duration_ms: int | None
    next_retry_at: datetime | None
    started_at: datetime
    finished_at: datetime | None


class DeliverySummary(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    external_event_id: str
    endpoint_id: uuid.UUID
    endpoint_name: str
    destination_id: uuid.UUID
    destination_name: str
    status: DeliveryStatus
    attempt_count: int
    max_attempts: int
    last_status_code: int | None
    last_error: str | None
    next_attempt_at: datetime | None
    replay_count: int
    created_at: datetime
    updated_at: datetime
    succeeded_at: datetime | None
    failed_at: datetime | None


class DeliveryDetail(DeliverySummary):
    transform_rule_id: uuid.UUID | None
    transformed_payload: Any | None
    attempts: list[AttemptOut]


class EventSummary(BaseModel):
    id: uuid.UUID
    endpoint_id: uuid.UUID
    endpoint_name: str
    external_event_id: str
    event_id_source: str
    status: EventStatus
    payload_size: int
    duplicate_count: int
    delivery_count: int
    received_at: datetime


class EventDetail(EventSummary):
    payload: Any
    headers: dict[str, str]
    source_ip: str | None
    last_duplicate_at: datetime | None
    deliveries: list[DeliverySummary]


class ReplayResponse(BaseModel):
    replayed: int
    delivery_ids: list[uuid.UUID]


class TimeBucket(BaseModel):
    bucket: datetime
    received: int
    succeeded: int
    failed: int


class DestinationHealth(BaseModel):
    destination_id: uuid.UUID
    destination_name: str
    succeeded: int
    failed: int
    pending: int
    success_rate: float | None


class DashboardSummary(BaseModel):
    period_hours: int
    events_received: int
    duplicates_blocked: int
    deliveries_total: int
    deliveries_succeeded: int
    deliveries_failed: int
    deliveries_pending: int
    deliveries_retrying: int
    success_rate: float | None
    avg_attempt_duration_ms: float | None
    outbox_pending: int
    timeline: list[TimeBucket]
    destinations: list[DestinationHealth]
    recent_failures: list[DeliverySummary]
