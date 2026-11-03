from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import AdminCtx, CurrentUser, DbSession, OrgCtx, get_owned
from app.api.routes.auth import unique_slug
from app.models import AuditLog, Membership, Organization, Role, User
from app.schemas.common import Page
from app.schemas.orgs import (
    AuditLogOut,
    MemberCreate,
    MemberOut,
    MemberUpdate,
    OrganizationCreate,
    OrganizationOut,
    OrganizationUpdate,
)
from app.services.common import record_audit

router = APIRouter(prefix="/orgs", tags=["organizations"])


def _member_out(m: Membership, u: User) -> MemberOut:
    return MemberOut(
        id=m.id, user_id=u.id, email=u.email, full_name=u.full_name, role=m.role, created_at=m.created_at
    )


@router.get("", response_model=list[OrganizationOut])
def list_orgs(user: CurrentUser, db: DbSession) -> list[OrganizationOut]:
    rows = db.execute(
        select(Organization, Membership.role)
        .join(Membership, Membership.organization_id == Organization.id)
        .where(Membership.user_id == user.id)
        .order_by(Organization.name)
    ).all()
    return [
        OrganizationOut(id=o.id, name=o.name, slug=o.slug, created_at=o.created_at, role=role)
        for o, role in rows
    ]


@router.post("", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
def create_org(body: OrganizationCreate, user: CurrentUser, db: DbSession) -> OrganizationOut:
    org = Organization(name=body.name.strip(), slug=unique_slug(db, body.name))
    db.add(org)
    db.flush()
    db.add(Membership(organization_id=org.id, user_id=user.id, role=Role.ADMIN))
    record_audit(
        db,
        organization_id=org.id,
        actor_user_id=user.id,
        action="organization.create",
        resource_type="organization",
        resource_id=org.id,
        details={"name": org.name},
    )
    db.commit()
    return OrganizationOut(
        id=org.id, name=org.name, slug=org.slug, created_at=org.created_at, role=Role.ADMIN
    )


@router.get("/{org_id}", response_model=OrganizationOut)
def get_org(ctx: OrgCtx) -> OrganizationOut:
    o = ctx.organization
    return OrganizationOut(
        id=o.id, name=o.name, slug=o.slug, created_at=o.created_at, role=ctx.membership.role
    )


@router.patch("/{org_id}", response_model=OrganizationOut)
def update_org(body: OrganizationUpdate, ctx: AdminCtx, db: DbSession) -> OrganizationOut:
    org = ctx.organization
    old = org.name
    org.name = body.name.strip()
    record_audit(
        db,
        organization_id=org.id,
        actor_user_id=ctx.user.id,
        action="organization.update",
        resource_type="organization",
        resource_id=org.id,
        details={"from": old, "to": org.name},
    )
    db.commit()
    return OrganizationOut(
        id=org.id, name=org.name, slug=org.slug, created_at=org.created_at, role=ctx.membership.role
    )


@router.get("/{org_id}/members", response_model=list[MemberOut])
def list_members(ctx: OrgCtx, db: DbSession) -> list[MemberOut]:
    rows = db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.organization_id == ctx.org_id)
        .order_by(User.full_name)
    ).all()
    return [_member_out(m, u) for m, u in rows]


@router.post("/{org_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def add_member(body: MemberCreate, ctx: AdminCtx, db: DbSession) -> MemberOut:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None:
        raise HTTPException(
            status_code=404, detail="usuário não encontrado — peça para a pessoa criar uma conta primeiro"
        )
    exists = db.scalar(
        select(Membership.id).where(Membership.organization_id == ctx.org_id, Membership.user_id == user.id)
    )
    if exists is not None:
        raise HTTPException(status_code=409, detail="usuário já é membro desta organização")
    membership = Membership(organization_id=ctx.org_id, user_id=user.id, role=body.role)
    db.add(membership)
    record_audit(
        db,
        organization_id=ctx.org_id,
        actor_user_id=ctx.user.id,
        action="member.add",
        resource_type="membership",
        resource_id=user.id,
        details={"email": user.email, "role": str(body.role)},
    )
    db.commit()
    return _member_out(membership, user)


def _admin_count(db: DbSession, org_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.organization_id == org_id, Membership.role == Role.ADMIN)
        )
        or 0
    )


@router.patch("/{org_id}/members/{membership_id}", response_model=MemberOut)
def update_member(membership_id: uuid.UUID, body: MemberUpdate, ctx: AdminCtx, db: DbSession) -> MemberOut:
    membership = get_owned(db, Membership, membership_id, ctx.org_id)
    if membership.role == Role.ADMIN and body.role != Role.ADMIN and _admin_count(db, ctx.org_id) <= 1:
        raise HTTPException(status_code=409, detail="a organização precisa de ao menos um ADMIN")
    old = membership.role
    membership.role = body.role
    record_audit(
        db,
        organization_id=ctx.org_id,
        actor_user_id=ctx.user.id,
        action="member.role_change",
        resource_type="membership",
        resource_id=membership.user_id,
        details={"from": str(old), "to": str(body.role)},
    )
    db.commit()
    user = db.get(User, membership.user_id)
    assert user is not None
    return _member_out(membership, user)


@router.delete("/{org_id}/members/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(membership_id: uuid.UUID, ctx: AdminCtx, db: DbSession) -> None:
    membership = get_owned(db, Membership, membership_id, ctx.org_id)
    if membership.role == Role.ADMIN and _admin_count(db, ctx.org_id) <= 1:
        raise HTTPException(status_code=409, detail="a organização precisa de ao menos um ADMIN")
    record_audit(
        db,
        organization_id=ctx.org_id,
        actor_user_id=ctx.user.id,
        action="member.remove",
        resource_type="membership",
        resource_id=membership.user_id,
    )
    db.delete(membership)
    db.commit()


@router.get("/{org_id}/audit-logs", response_model=Page[AuditLogOut])
def list_audit_logs(
    ctx: AdminCtx,
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    action: str | None = Query(None, max_length=80),
) -> Page[AuditLogOut]:
    base = select(AuditLog).where(AuditLog.organization_id == ctx.org_id)
    if action:
        base = base.where(AuditLog.action == action)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(
        base.add_columns(User.email)
        .outerjoin(User, User.id == AuditLog.actor_user_id)
        .order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [
        AuditLogOut(
            id=a.id,
            action=a.action,
            resource_type=a.resource_type,
            resource_id=a.resource_id,
            details=a.details,
            actor_user_id=a.actor_user_id,
            actor_email=email,
            created_at=a.created_at,
        )
        for a, email in rows
    ]
    return Page[AuditLogOut].build(items, int(total), page, page_size)
