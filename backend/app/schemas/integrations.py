from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import HttpMethod
from app.schemas.common import ORMModel

# Headers a user may NOT configure on a destination (hop-by-hop, framing or our own).
FORBIDDEN_HEADERS = {
    "host",
    "content-length",
    "content-type",
    "transfer-encoding",
    "connection",
    "keep-alive",
    "upgrade",
    "proxy-authorization",
    "proxy-connection",
    "te",
    "trailer",
    "expect",
    "cookie",
}
_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-]{0,63}$")
_EVENT_PATH_RE = re.compile(r"^[A-Za-z0-9_\-\.\[\]\$]{1,200}$")


def _validate_headers(value: dict[str, str]) -> dict[str, str]:
    if len(value) > 20:
        raise ValueError("máximo de 20 headers")
    clean: dict[str, str] = {}
    for name, header_value in value.items():
        if not _HEADER_NAME_RE.match(name):
            raise ValueError(f"nome de header inválido: {name}")
        lowered = name.lower()
        if lowered in FORBIDDEN_HEADERS or lowered.startswith("x-connecthub-"):
            raise ValueError(f"o header '{name}' é gerenciado pela plataforma")
        if not isinstance(header_value, str) or len(header_value) > 1024:
            raise ValueError(f"valor inválido para o header '{name}'")
        if "\r" in header_value or "\n" in header_value:
            raise ValueError(f"o header '{name}' contém quebra de linha")
        clean[name] = header_value
    return clean


# ------------------------------------------------------------------ endpoints
class EndpointCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    event_id_path: str = Field(default="id", max_length=200)
    is_active: bool = True

    @field_validator("event_id_path")
    @classmethod
    def _path(cls, v: str) -> str:
        if not _EVENT_PATH_RE.match(v):
            raise ValueError("caminho inválido para o identificador do evento")
        return v


class EndpointUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    event_id_path: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None

    @field_validator("event_id_path")
    @classmethod
    def _path(cls, v: str | None) -> str | None:
        if v is not None and not _EVENT_PATH_RE.match(v):
            raise ValueError("caminho inválido para o identificador do evento")
        return v


class RouteOut(ORMModel):
    id: uuid.UUID
    endpoint_id: uuid.UUID
    destination_id: uuid.UUID
    destination_name: str
    transform_rule_id: uuid.UUID | None
    transform_rule_name: str | None
    is_active: bool
    created_at: datetime


class EndpointOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None
    public_id: str
    ingest_url: str
    secret_preview: str
    secret_rotated_at: datetime | None
    previous_secret_expires_at: datetime | None
    event_id_path: str
    is_active: bool
    routes: list[RouteOut] = []
    created_at: datetime
    updated_at: datetime


class EndpointWithSecret(EndpointOut):
    signing_secret: str


class SecretOut(BaseModel):
    signing_secret: str
    previous_secret_expires_at: datetime | None = None


class RotateSecretRequest(BaseModel):
    grace_period_minutes: int = Field(default=60, ge=0, le=7 * 24 * 60)


class RouteCreate(BaseModel):
    destination_id: uuid.UUID
    transform_rule_id: uuid.UUID | None = None
    is_active: bool = True


class RouteUpdate(BaseModel):
    transform_rule_id: uuid.UUID | None = None
    clear_transform: bool = False
    is_active: bool | None = None


# ------------------------------------------------------------------ destinations
class DestinationBase(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    url: str = Field(min_length=8, max_length=2048)
    method: HttpMethod = HttpMethod.POST
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    max_attempts: int = Field(default=5, ge=1, le=20)
    is_active: bool = True

    _h = field_validator("headers")(_validate_headers)


class DestinationCreate(DestinationBase):
    signing_secret: str | None = Field(default=None, min_length=16, max_length=256)


class DestinationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    url: str | None = Field(default=None, min_length=8, max_length=2048)
    method: HttpMethod | None = None
    headers: dict[str, str] | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=60)
    max_attempts: int | None = Field(default=None, ge=1, le=20)
    is_active: bool | None = None
    signing_secret: str | None = Field(default=None, min_length=16, max_length=256)
    clear_signing_secret: bool = False

    @field_validator("headers")
    @classmethod
    def _h(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        return None if v is None else _validate_headers(v)


class DestinationOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None
    url: str
    method: HttpMethod
    headers: dict[str, str]
    timeout_seconds: int
    max_attempts: int
    is_active: bool
    has_signing_secret: bool
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------ transform rules
class Mapping(BaseModel):
    target: str = Field(min_length=1, max_length=200)
    source: str | None = Field(default=None, max_length=200)
    value: Any = None
    default: Any = None
    type: Literal["keep", "string", "integer", "float", "boolean", "datetime"] = "keep"
    transform: Literal["lower", "upper", "trim"] | None = None
    required: bool = False


class TransformRuleBase(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    include_unmapped: bool = False
    mappings: list[Mapping] = Field(default_factory=list, max_length=200)
    sample_payload: dict[str, Any] | None = None


class TransformRuleCreate(TransformRuleBase):
    pass


class TransformRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    include_unmapped: bool | None = None
    mappings: list[Mapping] | None = Field(default=None, max_length=200)
    sample_payload: dict[str, Any] | None = None


class TransformRuleOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None
    include_unmapped: bool
    mappings: list[dict[str, Any]]
    sample_payload: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class PreviewRequest(BaseModel):
    mappings: list[Mapping] = Field(default_factory=list, max_length=200)
    include_unmapped: bool = False
    sample_payload: Any


class PreviewResponse(BaseModel):
    valid: bool
    output: Any = None
    errors: list[str] = []
