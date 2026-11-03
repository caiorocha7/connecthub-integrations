from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import Role
from app.schemas.common import ORMModel

_PASSWORD_HELP = "a senha deve ter ao menos 8 caracteres, com letras e números"


def _validate_password(value: str) -> str:
    if len(value) < 8 or not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        raise ValueError(_PASSWORD_HELP)
    return value


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=160)
    organization_name: str | None = Field(default=None, min_length=2, max_length=160)

    _pw = field_validator("password")(_validate_password)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class MembershipSummary(BaseModel):
    organization_id: uuid.UUID
    organization_name: str
    organization_slug: str
    role: Role


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool
    created_at: datetime


class MeResponse(UserOut):
    memberships: list[MembershipSummary]


class UpdateProfileRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)

    _pw = field_validator("new_password")(_validate_password)
