"""Endpoints (inbound), destinations (outbound), routes and transformation rules."""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.deps import AdminCtx, DbSession, OrgCtx, get_owned
from app.core.config import get_settings
from app.core.security import (
    decrypt_secret,
    encrypt_secret,
    generate_public_id,
    generate_signing_secret,
    mask_secret,
)
from app.core.ssrf import UnsafeURLError, assert_safe_url
from app.models import Delivery, Destination, Endpoint, Event, Route, TransformRule
from app.schemas.integrations import (
    DestinationCreate,
    DestinationOut,
    DestinationUpdate,
    EndpointCreate,
    EndpointOut,
    EndpointUpdate,
    EndpointWithSecret,
    PreviewRequest,
    PreviewResponse,
    RotateSecretRequest,
    RouteCreate,
    RouteOut,
    RouteUpdate,
    SecretOut,
    TransformRuleCreate,
    TransformRuleOut,
    TransformRuleUpdate,
)
from app.services.common import record_audit, utcnow
from app.services.transform import RuleValidationError, TransformError, apply_rule, compile_rule

router = APIRouter(prefix="/orgs/{org_id}", tags=["integrations"])


def _commit_or_conflict(db: Session, message: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=message) from exc


# ======================================================================== endpoints
def _route_out(route: Route) -> RouteOut:
    return RouteOut(
        id=route.id,
        endpoint_id=route.endpoint_id,
        destination_id=route.destination_id,
        destination_name=route.destination.name,
        transform_rule_id=route.transform_rule_id,
        transform_rule_name=route.transform_rule.name if route.transform_rule else None,
        is_active=route.is_active,
        created_at=route.created_at,
    )


def _endpoint_out(endpoint: Endpoint) -> EndpointOut:
    base = get_settings().public_base_url.rstrip("/")
    return EndpointOut(
        id=endpoint.id,
        name=endpoint.name,
        description=endpoint.description,
        public_id=endpoint.public_id,
        ingest_url=f"{base}/api/v1/ingest/{endpoint.public_id}",
        secret_preview=mask_secret(decrypt_secret(endpoint.secret_encrypted)),
        secret_rotated_at=endpoint.secret_rotated_at,
        previous_secret_expires_at=endpoint.previous_secret_expires_at,
        event_id_path=endpoint.event_id_path,
        is_active=endpoint.is_active,
        routes=[_route_out(r) for r in endpoint.routes],
        created_at=endpoint.created_at,
        updated_at=endpoint.updated_at,
    )


def _load_endpoint(db: Session, endpoint_id: uuid.UUID, org_id: uuid.UUID) -> Endpoint:
    endpoint = db.scalar(
        select(Endpoint)
        .where(Endpoint.id == endpoint_id, Endpoint.organization_id == org_id)
        .options(
            selectinload(Endpoint.routes).selectinload(Route.destination),
            selectinload(Endpoint.routes).selectinload(Route.transform_rule),
        )
    )
    if endpoint is None:
        raise HTTPException(status_code=404, detail="recurso não encontrado")
    return endpoint


@router.get("/endpoints", response_model=list[EndpointOut])
def list_endpoints(ctx: OrgCtx, db: DbSession) -> list[EndpointOut]:
    endpoints = db.scalars(
        select(Endpoint)
        .where(Endpoint.organization_id == ctx.org_id)
        .options(
            selectinload(Endpoint.routes).selectinload(Route.destination),
            selectinload(Endpoint.routes).selectinload(Route.transform_rule),
        )
        .order_by(Endpoint.created_at.desc())
    ).all()
    return [_endpoint_out(e) for e in endpoints]


@router.post("/endpoints", response_model=EndpointWithSecret, status_code=status.HTTP_201_CREATED)
def create_endpoint(body: EndpointCreate, ctx: AdminCtx, db: DbSession) -> EndpointWithSecret:
    secret = generate_signing_secret()
    endpoint = Endpoint(
        organization_id=ctx.org_id,
        name=body.name.strip(),
        description=body.description,
        public_id=generate_public_id(),
        secret_encrypted=encrypt_secret(secret),
        event_id_path=body.event_id_path,
        is_active=body.is_active,
    )
    db.add(endpoint)
    db.flush()
    record_audit(
        db,
        organization_id=ctx.org_id,
        actor_user_id=ctx.user.id,
        action="endpoint.create",
        resource_type="endpoint",
        resource_id=endpoint.id,
        details={"name": endpoint.name},
    )
    _commit_or_conflict(db, "já existe um endpoint com este nome")
    out = _endpoint_out(_load_endpoint(db, endpoint.id, ctx.org_id))
    return EndpointWithSecret(**out.model_dump(), signing_secret=secret)


@router.get("/endpoints/{endpoint_id}", response_model=EndpointOut)
def get_endpoint(endpoint_id: uuid.UUID, ctx: OrgCtx, db: DbSession) -> EndpointOut:
    return _endpoint_out(_load_endpoint(db, endpoint_id, ctx.org_id))


@router.patch("/endpoints/{endpoint_id}", response_model=EndpointOut)
def update_endpoint(
    endpoint_id: uuid.UUID, body: EndpointUpdate, ctx: AdminCtx, db: DbSession
) -> EndpointOut:
    endpoint = _load_endpoint(db, endpoint_id, ctx.org_id)
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(endpoint, field, value.strip() if field == "name" and value else value)
    record_audit(
        db,
        organization_id=ctx.org_id,
        actor_user_id=ctx.user.id,
        action="endpoint.update",
        resource_type="endpoint",
        resource_id=endpoint.id,
        details={"changes": list(changes)},
    )
    _commit_or_conflict(db, "já existe um endpoint com este nome")
    return _endpoint_out(_load_endpoint(db, endpoint_id, ctx.org_id))


@router.delete("/endpoints/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_endpoint(endpoint_id: uuid.UUID, ctx: AdminCtx, db: DbSession) -> None:
    endpoint = get_owned(db, Endpoint, endpoint_id, ctx.org_id)
    has_events = db.scalar(select(func.count()).select_from(Event).where(Event.endpoint_id == endpoint.id))
    if has_events:
        raise HTTPException(
            status_code=409,
            detail="endpoint possui eventos no histórico; desative-o em vez de excluir",
        )
    record_audit(
        db,
        organization_id=ctx.org_id,
        actor_user_id=ctx.user.id,
        action="endpoint.delete",
        resource_type="endpoint",
        resource_id=endpoint.id,
        details={"name": endpoint.name},
    )
    db.delete(endpoint)
    db.commit()


@router.post("/endpoints/{endpoint_id}/rotate-secret", response_model=SecretOut)
def rotate_secret(
    endpoint_id: uuid.UUID, body: RotateSecretRequest, ctx: AdminCtx, db: DbSession
) -> SecretOut:
    endpoint = get_owned(db, Endpoint, endpoint_id, ctx.org_id)
    now = utcnow()
    new_secret = generate_signing_secret()
    if body.grace_period_minutes > 0:
        endpoint.previous_secret_encrypted = endpoint.secret_encrypted
        endpoint.previous_secret_expires_at = now + timedelta(minutes=body.grace_period_minutes)
    else:
        endpoint.previous_secret_encrypted = None
        endpoint.previous_secret_expires_at = None
    endpoint.secret_encrypted = encrypt_secret(new_secret)
    endpoint.secret_rotated_at = now
    record_audit(
        db,
        organization_id=ctx.org_id,
        actor_user_id=ctx.user.id,
        action="endpoint.rotate_secret",
        resource_type="endpoint",
        resource_id=endpoint.id,
        details={"grace_period_minutes": body.grace_period_minutes},
    )
    db.commit()
    return SecretOut(
        signing_secret=new_secret, previous_secret_expires_at=endpoint.previous_secret_expires_at
    )


@router.get("/endpoints/{endpoint_id}/secret", response_model=SecretOut)
def reveal_secret(endpoint_id: uuid.UUID, ctx: AdminCtx, db: DbSession) -> SecretOut:
    endpoint = get_owned(db, Endpoint, endpoint_id, ctx.org_id)
    record_audit(
        db,
        organization_id=ctx.org_id,
        actor_user_id=ctx.user.id,
        action="endpoint.reveal_secret",
        resource_type="endpoint",
        resource_id=endpoint.id,
    )
    db.commit()
    return SecretOut(
        signing_secret=decrypt_secret(endpoint.secret_encrypted),
        previous_secret_expires_at=endpoint.previous_secret_expires_at,
    )


# ------------------------------------------------------------------------ routes
@router.post("/endpoints/{endpoint_id}/routes", response_model=RouteOut, status_code=status.HTTP_201_CREATED)
def create_route(endpoint_id: uuid.UUID, body: RouteCreate, ctx: AdminCtx, db: DbSession) -> RouteOut:
    endpoint = get_owned(db, Endpoint, endpoint_id, ctx.org_id)
    destination = get_owned(db, Destination, body.destination_id, ctx.org_id)
    if body.transform_rule_id is not None:
        get_owned(db, TransformRule, body.transform_rule_id, ctx.org_id)
    route = Route(
        organization_id=ctx.org_id,
        endpoint_id=endpoint.id,
        destination_id=destination.id,
        transform_rule_id=body.transform_rule_id,
        is_active=body.is_active,
    )
    db.add(route)
    db.flush()
    record_audit(
        db,
        organization_id=ctx.org_id,
        actor_user_id=ctx.user.id,
        action="route.create",
        resource_type="route",
        resource_id=route.id,
        details={"endpoint": endpoint.name, "destination": destination.name},
    )
    _commit_or_conflict(db, "este destino já está associado ao endpoint")
    db.refresh(route)
    return _route_out(route)


@router.patch("/endpoints/{endpoint_id}/routes/{route_id}", response_model=RouteOut)
def update_route(
    endpoint_id: uuid.UUID, route_id: uuid.UUID, body: RouteUpdate, ctx: AdminCtx, db: DbSession
) -> RouteOut:
    route = get_owned(db, Route, route_id, ctx.org_id)
    if route.endpoint_id != endpoint_id:
        raise HTTPException(status_code=404, detail="recurso não encontrado")
    if body.clear_transform:
        route.transform_rule_id = None
    elif body.transform_rule_id is not None:
        get_owned(db, TransformRule, body.transform_rule_id, ctx.org_id)
        route.transform_rule_id = body.transform_rule_id
    if body.is_active is not None:
        route.is_active = body.is_active
    record_audit(
        db,
        organization_id=ctx.org_id,
        actor_user_id=ctx.user.id,
        action="route.update",
        resource_type="route",
        resource_id=route.id,
        details=body.model_dump(mode="json", exclude_unset=True),
    )
    db.commit()
    db.refresh(route)
    return _route_out(route)


@router.delete("/endpoints/{endpoint_id}/routes/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_route(endpoint_id: uuid.UUID, route_id: uuid.UUID, ctx: AdminCtx, db: DbSession) -> None:
    route = get_owned(db, Route, route_id, ctx.org_id)
    if route.endpoint_id != endpoint_id:
        raise HTTPException(status_code=404, detail="recurso não encontrado")
    record_audit(
        db,
        organization_id=ctx.org_id,
        actor_user_id=ctx.user.id,
        action="route.delete",
        resource_type="route",
        resource_id=route.id,
    )
    db.delete(route)
    db.commit()


# ======================================================================== destinations
def _destination_out(d: Destination) -> DestinationOut:
    return DestinationOut(
        id=d.id,
        name=d.name,
        description=d.description,
        url=d.url,
        method=d.method,
        headers=d.headers or {},
        timeout_seconds=d.timeout_seconds,
        max_attempts=d.max_attempts,
        is_active=d.is_active,
        has_signing_secret=d.signing_secret_encrypted is not None,
        created_at=d.created_at,
        updated_at=d.updated_at,
    )


def _check_url(url: str) -> str:
    try:
        assert_safe_url(url)
    except UnsafeURLError as exc:
        raise HTTPException(status_code=422, detail=f"URL de destino inválida: {exc}") from exc
    return url


@router.get("/destinations", response_model=list[DestinationOut])
def list_destinations(ctx: OrgCtx, db: DbSession) -> list[DestinationOut]:
    rows = db.scalars(
        select(Destination).where(Destination.organization_id == ctx.org_id).order_by(Destination.name)
    ).all()
    return [_destination_out(d) for d in rows]


@router.post("/destinations", response_model=DestinationOut, status_code=status.HTTP_201_CREATED)
def create_destination(body: DestinationCreate, ctx: AdminCtx, db: DbSession) -> DestinationOut:
    destination = Destination(
        organization_id=ctx.org_id,
        name=body.name.strip(),
        description=body.description,
        url=_check_url(body.url),
        method=body.method,
        headers=body.headers,
        timeout_seconds=body.timeout_seconds,
        max_attempts=body.max_attempts,
        is_active=body.is_active,
        signing_secret_encrypted=encrypt_secret(body.signing_secret) if body.signing_secret else None,
    )
    db.add(destination)
    db.flush()
    record_audit(
        db,
        organization_id=ctx.org_id,
        actor_user_id=ctx.user.id,
        action="destination.create",
        resource_type="destination",
        resource_id=destination.id,
        details={"name": destination.name, "url": destination.url},
    )
    _commit_or_conflict(db, "já existe um destino com este nome")
    db.refresh(destination)
    return _destination_out(destination)


@router.get("/destinations/{destination_id}", response_model=DestinationOut)
def get_destination(destination_id: uuid.UUID, ctx: OrgCtx, db: DbSession) -> DestinationOut:
    return _destination_out(get_owned(db, Destination, destination_id, ctx.org_id))


@router.patch("/destinations/{destination_id}", response_model=DestinationOut)
def update_destination(
    destination_id: uuid.UUID, body: DestinationUpdate, ctx: AdminCtx, db: DbSession
) -> DestinationOut:
    destination = get_owned(db, Destination, destination_id, ctx.org_id)
    changes = body.model_dump(exclude_unset=True, exclude={"signing_secret", "clear_signing_secret"})
    if "url" in changes and changes["url"] is not None:
        _check_url(changes["url"])
    for field, value in changes.items():
        if value is not None:
            setattr(destination, field, value)
    if body.clear_signing_secret:
        destination.signing_secret_encrypted = None
    elif body.signing_secret:
        destination.signing_secret_encrypted = encrypt_secret(body.signing_secret)
    record_audit(
        db,
        organization_id=ctx.org_id,
        actor_user_id=ctx.user.id,
        action="destination.update",
        resource_type="destination",
        resource_id=destination.id,
        details={"changes": list(body.model_dump(exclude_unset=True))},
    )
    _commit_or_conflict(db, "já existe um destino com este nome")
    db.refresh(destination)
    return _destination_out(destination)


@router.delete("/destinations/{destination_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_destination(destination_id: uuid.UUID, ctx: AdminCtx, db: DbSession) -> None:
    destination = get_owned(db, Destination, destination_id, ctx.org_id)
    has_deliveries = db.scalar(
        select(func.count()).select_from(Delivery).where(Delivery.destination_id == destination.id)
    )
    if has_deliveries:
        raise HTTPException(
            status_code=409,
            detail="destino possui entregas no histórico; desative-o em vez de excluir",
        )
    record_audit(
        db,
        organization_id=ctx.org_id,
        actor_user_id=ctx.user.id,
        action="destination.delete",
        resource_type="destination",
        resource_id=destination.id,
        details={"name": destination.name},
    )
    db.delete(destination)
    db.commit()


# ======================================================================== transform rules
def _validate_mappings(mappings: list[dict[str, object]], include_unmapped: bool) -> None:
    try:
        compile_rule(mappings, include_unmapped)
    except RuleValidationError as exc:
        raise HTTPException(
            status_code=422, detail={"message": "regra inválida", "errors": exc.errors}
        ) from exc


@router.get("/transform-rules", response_model=list[TransformRuleOut])
def list_rules(ctx: OrgCtx, db: DbSession) -> list[TransformRuleOut]:
    rows = db.scalars(
        select(TransformRule).where(TransformRule.organization_id == ctx.org_id).order_by(TransformRule.name)
    ).all()
    return [TransformRuleOut.model_validate(r) for r in rows]


@router.post("/transform-rules", response_model=TransformRuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(body: TransformRuleCreate, ctx: AdminCtx, db: DbSession) -> TransformRuleOut:
    mappings = [m.model_dump(exclude_none=True) for m in body.mappings]
    _validate_mappings(mappings, body.include_unmapped)
    rule = TransformRule(
        organization_id=ctx.org_id,
        name=body.name.strip(),
        description=body.description,
        include_unmapped=body.include_unmapped,
        mappings=mappings,
        sample_payload=body.sample_payload,
    )
    db.add(rule)
    db.flush()
    record_audit(
        db,
        organization_id=ctx.org_id,
        actor_user_id=ctx.user.id,
        action="transform_rule.create",
        resource_type="transform_rule",
        resource_id=rule.id,
        details={"name": rule.name, "mappings": len(mappings)},
    )
    _commit_or_conflict(db, "já existe uma regra com este nome")
    db.refresh(rule)
    return TransformRuleOut.model_validate(rule)


@router.get("/transform-rules/{rule_id}", response_model=TransformRuleOut)
def get_rule(rule_id: uuid.UUID, ctx: OrgCtx, db: DbSession) -> TransformRuleOut:
    return TransformRuleOut.model_validate(get_owned(db, TransformRule, rule_id, ctx.org_id))


@router.patch("/transform-rules/{rule_id}", response_model=TransformRuleOut)
def update_rule(
    rule_id: uuid.UUID, body: TransformRuleUpdate, ctx: AdminCtx, db: DbSession
) -> TransformRuleOut:
    rule = get_owned(db, TransformRule, rule_id, ctx.org_id)
    changes = body.model_dump(exclude_unset=True)
    if body.mappings is not None:
        rule.mappings = [m.model_dump(exclude_none=True) for m in body.mappings]
    for field in ("name", "description", "include_unmapped", "sample_payload"):
        if field in changes:
            setattr(rule, field, changes[field])
    _validate_mappings(rule.mappings, rule.include_unmapped)
    record_audit(
        db,
        organization_id=ctx.org_id,
        actor_user_id=ctx.user.id,
        action="transform_rule.update",
        resource_type="transform_rule",
        resource_id=rule.id,
        details={"changes": list(changes)},
    )
    _commit_or_conflict(db, "já existe uma regra com este nome")
    db.refresh(rule)
    return TransformRuleOut.model_validate(rule)


@router.delete("/transform-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: uuid.UUID, ctx: AdminCtx, db: DbSession) -> None:
    rule = get_owned(db, TransformRule, rule_id, ctx.org_id)
    record_audit(
        db,
        organization_id=ctx.org_id,
        actor_user_id=ctx.user.id,
        action="transform_rule.delete",
        resource_type="transform_rule",
        resource_id=rule.id,
        details={"name": rule.name},
    )
    db.delete(rule)
    db.commit()


@router.post("/transform-rules/preview", response_model=PreviewResponse)
def preview_rule(body: PreviewRequest, ctx: OrgCtx) -> PreviewResponse:
    mappings = [m.model_dump(exclude_none=True) for m in body.mappings]
    try:
        compiled = compile_rule(mappings, body.include_unmapped)
    except RuleValidationError as exc:
        return PreviewResponse(valid=False, errors=exc.errors)
    try:
        output = apply_rule(compiled, body.sample_payload)
    except TransformError as exc:
        return PreviewResponse(valid=False, errors=[str(exc)])
    return PreviewResponse(valid=True, output=output)
