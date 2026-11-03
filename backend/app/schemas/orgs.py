from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import Role
from app.schemas.common import ORMModel


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)


class OrganizationUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=160)


class OrganizationOut(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime
    role: Role | None = None


class MemberOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    full_name: str
    role: Role
    created_at: datetime


class MemberCreate(BaseModel):
    email: EmailStr
    role: Role = Role.OPERATOR


class MemberUpdate(BaseModel):
    role: Role


class AuditLogOut(ORMModel):
    id: uuid.UUID
    action: str
    resource_type: str
    resource_id: str | None
    details: dict[str, Any]
    actor_user_id: uuid.UUID | None
    actor_email: str | None = None
    created_at: datetime
