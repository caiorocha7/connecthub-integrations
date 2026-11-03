from __future__ import annotations

import re
import secrets
import unicodedata
from datetime import timedelta

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.models import Membership, Organization, RefreshToken, Role, User
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    MembershipSummary,
    MeResponse,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UpdateProfileRequest,
)
from app.services.common import record_audit, utcnow

router = APIRouter(prefix="/auth", tags=["auth"])

# Used to equalize timing when the e-mail does not exist.
_DUMMY_HASH = hash_password("timing-equalizer-password-1")


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return (slug or "org")[:60]


def unique_slug(db: Session, name: str) -> str:
    base = slugify(name)
    slug = base
    while db.scalar(select(Organization.id).where(Organization.slug == slug)) is not None:
        slug = f"{base}-{secrets.token_hex(3)}"
    return slug


def issue_tokens(db: Session, user: User) -> TokenResponse:
    settings = get_settings()
    access, expires_in = create_access_token(user.id)
    refresh = generate_refresh_token()
    now = utcnow()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(refresh),
            created_at=now,
            expires_at=now + timedelta(days=settings.refresh_token_expire_days),
        )
    )
    return TokenResponse(access_token=access, refresh_token=refresh, expires_in=expires_in)


def build_me(db: Session, user: User) -> MeResponse:
    rows = db.execute(
        select(Membership, Organization)
        .join(Organization, Organization.id == Membership.organization_id)
        .where(Membership.user_id == user.id)
        .order_by(Organization.name)
    ).all()
    return MeResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        created_at=user.created_at,
        memberships=[
            MembershipSummary(
                organization_id=org.id,
                organization_name=org.name,
                organization_slug=org.slug,
                role=m.role,
            )
            for m, org in rows
        ],
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: DbSession) -> TokenResponse:
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="e-mail já cadastrado")
    user = User(email=email, full_name=body.full_name.strip(), password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    org_name = body.organization_name or f"{body.full_name.split()[0]} Workspace"
    org = Organization(name=org_name.strip(), slug=unique_slug(db, org_name))
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
    tokens = issue_tokens(db, user)
    db.commit()
    return tokens


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: DbSession) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None:
        verify_password(body.password, _DUMMY_HASH)
        raise HTTPException(status_code=401, detail="e-mail ou senha inválidos")
    if not verify_password(body.password, user.password_hash) or not user.is_active:
        raise HTTPException(status_code=401, detail="e-mail ou senha inválidos")
    tokens = issue_tokens(db, user)
    db.commit()
    return tokens


@router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, db: DbSession) -> TokenResponse:
    """Rotate the refresh token: the old one is revoked and a new pair is issued."""
    now = utcnow()
    stored = db.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_token(body.refresh_token))
        .with_for_update()
    )
    if stored is None or stored.revoked_at is not None or stored.expires_at <= now:
        if stored is not None and stored.revoked_at is not None:
            # reuse of a revoked token: revoke the whole family for safety
            db.execute(
                update(RefreshToken)
                .where(RefreshToken.user_id == stored.user_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            db.commit()
        raise HTTPException(status_code=401, detail="sessão expirada, faça login novamente")
    user = db.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="sessão expirada, faça login novamente")
    stored.revoked_at = now
    tokens = issue_tokens(db, user)
    db.commit()
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(body: RefreshRequest, db: DbSession) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == hash_token(body.refresh_token), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    db.commit()


@router.get("/me", response_model=MeResponse)
def me(user: CurrentUser, db: DbSession) -> MeResponse:
    return build_me(db, user)


@router.patch("/me", response_model=MeResponse)
def update_me(body: UpdateProfileRequest, user: CurrentUser, db: DbSession) -> MeResponse:
    user.full_name = body.full_name.strip()
    db.commit()
    return build_me(db, user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: ChangePasswordRequest, user: CurrentUser, db: DbSession) -> None:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="senha atual incorreta")
    user.password_hash = hash_password(body.new_password)
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    db.commit()
