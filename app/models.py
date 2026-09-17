"""Pydantic v2 request/response models (API boundary)."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, HttpUrl, field_validator

# Custom alias: URL-safe chars, reasonable length for short links
AliasStr = Annotated[str, Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


class CreateLinkRequest(BaseModel):
    url: HttpUrl
    alias: AliasStr | None = None

    @field_validator("url", mode="before")
    @classmethod
    def coerce_url_str(cls, v: object) -> object:
        return v


class LinkCreatedResponse(BaseModel):
    code: str
    url: str
    short_url: str
    created_at: datetime
    clicks: int = 0
    active: bool = True


class LinkMetadataResponse(BaseModel):
    code: str
    url: str
    short_url: str
    created_at: datetime
    clicks: int
    active: bool


class HealthResponse(BaseModel):
    status: str = "ok"


class ErrorBody(BaseModel):
    error: str
    detail: str | None = None
    code: str | None = None
