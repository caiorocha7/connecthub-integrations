"""Authentication and tenant-scoped authorization dependencies."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated, Any, TypeVar

from fastapi import Depends, HTTPException, Path, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import TokenError, decode_access_token
from app.db.session import get_db
from app.models import Membership, Organization, Role, User

bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="não autenticado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(payload["sub"])
    except (TokenError, ValueError, KeyError):
        raise unauthorized from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


@dataclass
class OrgContext:
    organization: Organization
    membership: Membership
    user: User

    @property
    def org_id(self) -> uuid.UUID:
        return self.organization.id

    @property
    def is_admin(self) -> bool:
        return self.membership.role == Role.ADMIN


def get_org_context(
    org_id: Annotated[uuid.UUID, Path()],
    user: CurrentUser,
    db: DbSession,
) -> OrgContext:
    row = db.execute(
        select(Membership, Organization)
        .join(Organization, Organization.id == Membership.organization_id)
        .where(Membership.organization_id == org_id, Membership.user_id == user.id)
    ).first()
    if row is None:
        # 404 instead of 403: do not reveal the existence of other tenants' organizations
        raise HTTPException(status_code=404, detail="organização não encontrada")
    membership, organization = row
    return OrgContext(organization=organization, membership=membership, user=user)


def require_admin(ctx: Annotated[OrgContext, Depends(get_org_context)]) -> OrgContext:
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="ação permitida apenas para ADMIN")
    return ctx


OrgCtx = Annotated[OrgContext, Depends(get_org_context)]
AdminCtx = Annotated[OrgContext, Depends(require_admin)]

M = TypeVar("M")


def get_owned(db: Session, model: type[M], resource_id: uuid.UUID, org_id: uuid.UUID) -> M:
    """Fetch a tenant-owned resource or raise 404 (never leaks other tenants' data)."""
    obj: Any = db.get(model, resource_id)
    if obj is None or obj.organization_id != org_id:
        raise HTTPException(status_code=404, detail="recurso não encontrado")
    return obj  # type: ignore[no-any-return]
