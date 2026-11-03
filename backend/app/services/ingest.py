"""Webhook ingestion: authenticate (HMAC), deduplicate (idempotency key) and persist durably."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decrypt_secret, verify_signature
from app.models import Delivery, Destination, Endpoint, Event, EventStatus, Route
from app.services.common import utcnow
from app.services.outbox import enqueue_delivery
from app.services.transform import extract_value

logger = logging.getLogger(__name__)

HEADER_SIGNATURE = "x-connecthub-signature"
HEADER_TIMESTAMP = "x-connecthub-timestamp"
HEADER_EVENT_ID = "x-connecthub-event-id"
STORED_HEADERS = ("content-type", "user-agent", HEADER_EVENT_ID, HEADER_TIMESTAMP)
MAX_EVENT_ID_LENGTH = 255


class IngestError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class IngestResult:
    event_id: uuid.UUID
    external_event_id: str
    duplicate: bool
    status: str
    deliveries: int
    outbox_ids: list[uuid.UUID] = field(default_factory=list)


def _verify_request(endpoint: Endpoint, raw_body: bytes, headers: Mapping[str, str]) -> None:
    settings = get_settings()
    timestamp = headers.get(HEADER_TIMESTAMP)
    signature = headers.get(HEADER_SIGNATURE)
    if not timestamp or not signature:
        raise IngestError(401, "cabeçalhos de assinatura ausentes")
    try:
        ts_value = int(timestamp)
    except ValueError as exc:
        raise IngestError(401, "timestamp de assinatura inválido") from exc
    now = utcnow()
    if abs(now.timestamp() - ts_value) > settings.signature_tolerance_seconds:
        raise IngestError(401, "timestamp fora da janela de tolerância (possível replay)")

    secrets = [decrypt_secret(endpoint.secret_encrypted)]
    if (
        endpoint.previous_secret_encrypted
        and endpoint.previous_secret_expires_at
        and endpoint.previous_secret_expires_at > now
    ):
        secrets.append(decrypt_secret(endpoint.previous_secret_encrypted))
    if not verify_signature(secrets, timestamp, raw_body, signature):
        raise IngestError(401, "assinatura inválida")


def _resolve_event_id(
    endpoint: Endpoint, payload: object, raw_body: bytes, headers: Mapping[str, str]
) -> tuple[str, str]:
    header_id = headers.get(HEADER_EVENT_ID)
    if header_id:
        return header_id.strip()[:MAX_EVENT_ID_LENGTH], "header"
    value = extract_value(payload, endpoint.event_id_path)
    if isinstance(value, str | int) and not isinstance(value, bool) and str(value).strip():
        return str(value).strip()[:MAX_EVENT_ID_LENGTH], "payload"
    return "sha256:" + hashlib.sha256(raw_body).hexdigest(), "body_hash"


def ingest_webhook(
    db: Session,
    *,
    public_id: str,
    raw_body: bytes,
    headers: Mapping[str, str],
    source_ip: str | None,
) -> IngestResult:
    endpoint = db.scalar(select(Endpoint).where(Endpoint.public_id == public_id))
    if endpoint is None or not endpoint.is_active:
        raise IngestError(404, "endpoint não encontrado ou inativo")

    _verify_request(endpoint, raw_body, headers)

    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IngestError(400, "o corpo da requisição deve ser um JSON válido") from exc
    if not isinstance(payload, dict | list):
        raise IngestError(400, "o JSON deve ser um objeto ou uma lista")

    external_id, id_source = _resolve_event_id(endpoint, payload, raw_body, headers)
    stored_headers = {k: headers[k] for k in STORED_HEADERS if k in headers}
    now: datetime = utcnow()
    new_event_id = uuid.uuid4()

    inserted = db.execute(
        pg_insert(Event)
        .values(
            id=new_event_id,
            organization_id=endpoint.organization_id,
            endpoint_id=endpoint.id,
            external_event_id=external_id,
            event_id_source=id_source,
            status=EventStatus.RECEIVED,
            payload=payload,
            payload_size=len(raw_body),
            headers=stored_headers,
            source_ip=source_ip,
            duplicate_count=0,
            received_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_event_idempotency")
        .returning(Event.id)
    ).scalar_one_or_none()

    if inserted is None:
        existing_id = db.execute(
            update(Event)
            .where(
                Event.organization_id == endpoint.organization_id,
                Event.endpoint_id == endpoint.id,
                Event.external_event_id == external_id,
            )
            .values(duplicate_count=Event.duplicate_count + 1, last_duplicate_at=now)
            .returning(Event.id)
        ).scalar_one()
        delivery_count = db.scalar(
            select(func.count()).select_from(Delivery).where(Delivery.event_id == existing_id)
        )
        existing_status = db.scalar(select(Event.status).where(Event.id == existing_id))
        db.commit()
        logger.info(
            "duplicate event ignored",
            extra={"event_id": str(existing_id), "external_event_id": external_id},
        )
        return IngestResult(
            event_id=existing_id,
            external_event_id=external_id,
            duplicate=True,
            status=str(existing_status),
            deliveries=int(delivery_count or 0),
        )

    routes = db.execute(
        select(Route, Destination)
        .join(Destination, Destination.id == Route.destination_id)
        .where(
            Route.endpoint_id == endpoint.id,
            Route.organization_id == endpoint.organization_id,
            Route.is_active.is_(True),
            Destination.is_active.is_(True),
        )
    ).all()

    outbox_ids: list[uuid.UUID] = []
    for route, destination in routes:
        delivery = Delivery(
            id=uuid.uuid4(),
            organization_id=endpoint.organization_id,
            event_id=new_event_id,
            destination_id=destination.id,
            route_id=route.id,
            transform_rule_id=route.transform_rule_id,
            max_attempts=destination.max_attempts,
            next_attempt_at=now,
        )
        db.add(delivery)
        outbox_ids.append(enqueue_delivery(db, delivery, available_at=now).id)

    status = EventStatus.RECEIVED if routes else EventStatus.IGNORED
    if not routes:
        db.execute(update(Event).where(Event.id == new_event_id).values(status=status))
    db.commit()
    logger.info(
        "event persisted",
        extra={
            "event_id": str(new_event_id),
            "external_event_id": external_id,
            "deliveries": len(routes),
        },
    )
    return IngestResult(
        event_id=new_event_id,
        external_event_id=external_id,
        duplicate=False,
        status=str(status),
        deliveries=len(routes),
        outbox_ids=outbox_ids,
    )
