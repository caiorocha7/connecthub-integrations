"""Event history, delivery history, manual replay and dashboard metrics."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from sqlalchemy import Select, and_, case, func, select
from sqlalchemy.orm import Session

from app.api.deps import DbSession, OrgCtx
from app.core.masking import mask_sensitive
from app.models import (
    AttemptOutcome,
    Delivery,
    DeliveryAttempt,
    DeliveryStatus,
    Destination,
    Endpoint,
    Event,
    EventStatus,
    OutboxMessage,
    OutboxStatus,
)
from app.schemas.common import Page
from app.schemas.events import (
    AttemptOut,
    DashboardSummary,
    DeliveryDetail,
    DeliverySummary,
    DestinationHealth,
    EventDetail,
    EventSummary,
    ReplayResponse,
    TimeBucket,
)
from app.services.common import utcnow
from app.services.recovery import ReplayError, replay_delivery

router = APIRouter(prefix="/orgs/{org_id}", tags=["events"])


def _dispatch(background: BackgroundTasks, delivery_ids: list[uuid.UUID], db: Session) -> None:
    from app.worker.tasks import dispatch_now

    outbox_ids = list(
        db.scalars(
            select(OutboxMessage.id).where(
                OutboxMessage.aggregate_id.in_(delivery_ids),
                OutboxMessage.status == OutboxStatus.PENDING,
            )
        )
    )
    if outbox_ids:
        background.add_task(dispatch_now, outbox_ids)


# ------------------------------------------------------------------ delivery helpers
def _delivery_query(org_id: uuid.UUID) -> Select[Delivery, str, uuid.UUID, str, str]:
    stmt = (
        select(Delivery, Event.external_event_id, Event.endpoint_id, Endpoint.name, Destination.name)
        .join(Event, Event.id == Delivery.event_id)
        .join(Endpoint, Endpoint.id == Event.endpoint_id)
        .join(Destination, Destination.id == Delivery.destination_id)
        .where(Delivery.organization_id == org_id)
    )
    return stmt


def _delivery_summary(row: Any) -> DeliverySummary:
    d, external_id, endpoint_id, endpoint_name, destination_name = row
    return DeliverySummary(
        id=d.id,
        event_id=d.event_id,
        external_event_id=external_id,
        endpoint_id=endpoint_id,
        endpoint_name=endpoint_name,
        destination_id=d.destination_id,
        destination_name=destination_name,
        status=d.status,
        attempt_count=d.attempt_count,
        max_attempts=d.max_attempts,
        last_status_code=d.last_status_code,
        last_error=d.last_error,
        next_attempt_at=d.next_attempt_at,
        replay_count=d.replay_count,
        created_at=d.created_at,
        updated_at=d.updated_at,
        succeeded_at=d.succeeded_at,
        failed_at=d.failed_at,
    )


# ------------------------------------------------------------------ events
@router.get("/events", response_model=Page[EventSummary])
def list_events(
    ctx: OrgCtx,
    db: DbSession,
    status: EventStatus | None = None,
    endpoint_id: uuid.UUID | None = None,
    destination_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search: str | None = Query(None, max_length=255),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Page[EventSummary]:
    delivery_count = (
        select(func.count()).where(Delivery.event_id == Event.id).correlate(Event).scalar_subquery()
    )
    base = (
        select(Event, Endpoint.name, delivery_count)
        .join(Endpoint, Endpoint.id == Event.endpoint_id)
        .where(Event.organization_id == ctx.org_id)
    )
    if status:
        base = base.where(Event.status == status)
    if endpoint_id:
        base = base.where(Event.endpoint_id == endpoint_id)
    if destination_id:
        base = base.where(
            select(Delivery.id)
            .where(Delivery.event_id == Event.id, Delivery.destination_id == destination_id)
            .exists()
        )
    if date_from:
        base = base.where(Event.received_at >= date_from)
    if date_to:
        base = base.where(Event.received_at <= date_to)
    if search:
        base = base.where(Event.external_event_id.ilike(f"%{search}%"))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(
        base.order_by(Event.received_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    items = [
        EventSummary(
            id=e.id,
            endpoint_id=e.endpoint_id,
            endpoint_name=endpoint_name,
            external_event_id=e.external_event_id,
            event_id_source=e.event_id_source,
            status=e.status,
            payload_size=e.payload_size,
            duplicate_count=e.duplicate_count,
            delivery_count=count or 0,
            received_at=e.received_at,
        )
        for e, endpoint_name, count in rows
    ]
    return Page[EventSummary].build(items, int(total), page, page_size)


@router.get("/events/{event_id}", response_model=EventDetail)
def get_event(event_id: uuid.UUID, ctx: OrgCtx, db: DbSession) -> EventDetail:
    row = db.execute(
        select(Event, Endpoint.name)
        .join(Endpoint, Endpoint.id == Event.endpoint_id)
        .where(Event.id == event_id, Event.organization_id == ctx.org_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="recurso não encontrado")
    event, endpoint_name = row
    deliveries = [
        _delivery_summary(r)
        for r in db.execute(
            _delivery_query(ctx.org_id).where(Delivery.event_id == event.id).order_by(Delivery.created_at)
        ).all()
    ]
    return EventDetail(
        id=event.id,
        endpoint_id=event.endpoint_id,
        endpoint_name=endpoint_name,
        external_event_id=event.external_event_id,
        event_id_source=event.event_id_source,
        status=event.status,
        payload_size=event.payload_size,
        duplicate_count=event.duplicate_count,
        delivery_count=len(deliveries),
        received_at=event.received_at,
        payload=mask_sensitive(event.payload),
        headers=mask_sensitive(event.headers or {}),
        source_ip=event.source_ip,
        last_duplicate_at=event.last_duplicate_at,
        deliveries=deliveries,
    )


@router.post("/events/{event_id}/replay", response_model=ReplayResponse)
def replay_event(
    event_id: uuid.UUID, ctx: OrgCtx, db: DbSession, background: BackgroundTasks
) -> ReplayResponse:
    event = db.scalar(select(Event).where(Event.id == event_id, Event.organization_id == ctx.org_id))
    if event is None:
        raise HTTPException(status_code=404, detail="recurso não encontrado")
    failed_ids = list(
        db.scalars(
            select(Delivery.id).where(Delivery.event_id == event.id, Delivery.status == DeliveryStatus.FAILED)
        )
    )
    if not failed_ids:
        raise HTTPException(status_code=409, detail="o evento não possui entregas com falha")
    for delivery_id in failed_ids:
        replay_delivery(db, delivery_id, ctx.org_id, ctx.user.id)
    db.commit()
    _dispatch(background, failed_ids, db)
    return ReplayResponse(replayed=len(failed_ids), delivery_ids=failed_ids)


# ------------------------------------------------------------------ deliveries
@router.get("/deliveries", response_model=Page[DeliverySummary])
def list_deliveries(
    ctx: OrgCtx,
    db: DbSession,
    status: DeliveryStatus | None = None,
    endpoint_id: uuid.UUID | None = None,
    destination_id: uuid.UUID | None = None,
    event_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Page[DeliverySummary]:
    base = _delivery_query(ctx.org_id)
    if status:
        base = base.where(Delivery.status == status)
    if endpoint_id:
        base = base.where(Event.endpoint_id == endpoint_id)
    if destination_id:
        base = base.where(Delivery.destination_id == destination_id)
    if event_id:
        base = base.where(Delivery.event_id == event_id)
    if date_from:
        base = base.where(Delivery.created_at >= date_from)
    if date_to:
        base = base.where(Delivery.created_at <= date_to)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(
        base.order_by(Delivery.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return Page[DeliverySummary].build([_delivery_summary(r) for r in rows], int(total), page, page_size)


@router.get("/deliveries/{delivery_id}", response_model=DeliveryDetail)
def get_delivery(delivery_id: uuid.UUID, ctx: OrgCtx, db: DbSession) -> DeliveryDetail:
    row = db.execute(_delivery_query(ctx.org_id).where(Delivery.id == delivery_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="recurso não encontrado")
    delivery = row[0]
    attempts = db.scalars(
        select(DeliveryAttempt)
        .where(DeliveryAttempt.delivery_id == delivery.id)
        .order_by(DeliveryAttempt.attempt_number)
    ).all()
    summary = _delivery_summary(row)
    return DeliveryDetail(
        **summary.model_dump(),
        transform_rule_id=delivery.transform_rule_id,
        transformed_payload=mask_sensitive(delivery.transformed_payload),
        attempts=[AttemptOut.model_validate(a) for a in attempts],
    )


@router.post("/deliveries/{delivery_id}/replay", response_model=ReplayResponse)
def replay_single_delivery(
    delivery_id: uuid.UUID, ctx: OrgCtx, db: DbSession, background: BackgroundTasks
) -> ReplayResponse:
    try:
        replay_delivery(db, delivery_id, ctx.org_id, ctx.user.id)
    except LookupError:
        raise HTTPException(status_code=404, detail="recurso não encontrado") from None
    except ReplayError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    db.commit()
    _dispatch(background, [delivery_id], db)
    return ReplayResponse(replayed=1, delivery_ids=[delivery_id])


# ------------------------------------------------------------------ dashboard
@router.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(
    ctx: OrgCtx, db: DbSession, hours: int = Query(24, ge=1, le=24 * 30)
) -> DashboardSummary:
    now = utcnow()
    since = now - timedelta(hours=hours)
    org = ctx.org_id

    events_received, duplicates = db.execute(
        select(func.count(), func.coalesce(func.sum(Event.duplicate_count), 0)).where(
            Event.organization_id == org, Event.received_at >= since
        )
    ).one()

    status_counts = dict(
        db.execute(
            select(Delivery.status, func.count())
            .where(Delivery.organization_id == org, Delivery.created_at >= since)
            .group_by(Delivery.status)
        ).all()
    )
    succeeded = int(status_counts.get(DeliveryStatus.SUCCEEDED, 0))
    failed = int(status_counts.get(DeliveryStatus.FAILED, 0))
    retrying = int(status_counts.get(DeliveryStatus.RETRYING, 0))
    pending = int(
        status_counts.get(DeliveryStatus.PENDING, 0)
        + status_counts.get(DeliveryStatus.PROCESSING, 0)
        + retrying
    )
    finished = succeeded + failed
    avg_duration = db.scalar(
        select(func.avg(DeliveryAttempt.duration_ms)).where(
            DeliveryAttempt.organization_id == org,
            DeliveryAttempt.started_at >= since,
            DeliveryAttempt.outcome != AttemptOutcome.IN_PROGRESS,
        )
    )
    outbox_pending = db.scalar(
        select(func.count())
        .select_from(OutboxMessage)
        .where(OutboxMessage.organization_id == org, OutboxMessage.status == OutboxStatus.PENDING)
    )

    bucket_size = "hour" if hours <= 72 else "day"
    ev_bucket = func.date_trunc(bucket_size, Event.received_at)
    received_rows: dict[datetime, int] = dict(
        db.execute(
            select(ev_bucket, func.count())
            .where(Event.organization_id == org, Event.received_at >= since)
            .group_by(ev_bucket)
        ).all()
    )
    finished_at = func.coalesce(Delivery.succeeded_at, Delivery.failed_at)
    dl_bucket = func.date_trunc(bucket_size, finished_at)
    delivery_rows = {
        b: (s, f)
        for b, s, f in db.execute(
            select(
                dl_bucket,
                func.count().filter(Delivery.status == DeliveryStatus.SUCCEEDED),
                func.count().filter(Delivery.status == DeliveryStatus.FAILED),
            )
            .where(Delivery.organization_id == org, finished_at >= since)
            .group_by(dl_bucket)
        ).all()
    }
    step = timedelta(hours=1) if bucket_size == "hour" else timedelta(days=1)
    cursor = since.replace(minute=0, second=0, microsecond=0)
    if bucket_size == "day":
        cursor = cursor.replace(hour=0)
    timeline: list[TimeBucket] = []
    while cursor <= now:
        s, f = delivery_rows.get(cursor, (0, 0))
        timeline.append(
            TimeBucket(
                bucket=cursor, received=int(received_rows.get(cursor, 0)), succeeded=int(s), failed=int(f)
            )
        )
        cursor += step

    health_rows = db.execute(
        select(
            Destination.id,
            Destination.name,
            func.count(Delivery.id).filter(Delivery.status == DeliveryStatus.SUCCEEDED),
            func.count(Delivery.id).filter(Delivery.status == DeliveryStatus.FAILED),
            func.count(Delivery.id).filter(
                Delivery.status.in_(
                    [DeliveryStatus.PENDING, DeliveryStatus.PROCESSING, DeliveryStatus.RETRYING]
                )
            ),
        )
        .outerjoin(Delivery, and_(Delivery.destination_id == Destination.id, Delivery.created_at >= since))
        .where(Destination.organization_id == org)
        .group_by(Destination.id, Destination.name)
        .order_by(Destination.name)
    ).all()
    destinations = [
        DestinationHealth(
            destination_id=did,
            destination_name=name,
            succeeded=int(s),
            failed=int(f),
            pending=int(p),
            success_rate=round(s / (s + f) * 100, 1) if (s + f) else None,
        )
        for did, name, s, f, p in health_rows
    ]
    recent = db.execute(
        _delivery_query(org)
        .where(Delivery.status.in_([DeliveryStatus.FAILED, DeliveryStatus.RETRYING]))
        .order_by(
            case((Delivery.status == DeliveryStatus.FAILED, 0), else_=1),
            Delivery.updated_at.desc(),
        )
        .limit(8)
    ).all()
    return DashboardSummary(
        period_hours=hours,
        events_received=int(events_received),
        duplicates_blocked=int(duplicates),
        deliveries_total=int(sum(status_counts.values())),
        deliveries_succeeded=succeeded,
        deliveries_failed=failed,
        deliveries_pending=pending,
        deliveries_retrying=retrying,
        success_rate=round(succeeded / finished * 100, 1) if finished else None,
        avg_attempt_duration_ms=round(float(avg_duration), 1) if avg_duration is not None else None,
        outbox_pending=int(outbox_pending or 0),
        timeline=timeline,
        destinations=destinations,
        recent_failures=[_delivery_summary(r) for r in recent],
    )
