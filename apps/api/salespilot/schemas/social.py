"""Pydantic schemas for the social-content scheduler."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---- Destinations -----------------------------------------------------


class Destination(BaseModel):
    platform: Literal["linkedin"] = "linkedin"
    target_type: Literal["person", "organization"]
    target_urn: str
    target_name: str


# ---- Media -----------------------------------------------------------


class MediaPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    position: int
    filename: str
    mime_type: str
    size_bytes: int
    alt_text: str | None = None
    caption: str | None = None
    # Public URL the frontend can render. Built dynamically in the API.
    url: str = ""


# ---- Posts -----------------------------------------------------------


class PostUpsert(BaseModel):
    """Used for create + update. All fields optional on update."""
    title: str | None = None
    body: str
    destinations: list[Destination] = Field(default_factory=list)
    scheduled_at: datetime | None = None
    # Drafts have status='draft'; if the user wants to actually queue it,
    # they send status='scheduled' AND a scheduled_at.
    status: Literal["draft", "scheduled"] = "draft"


class PostUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    destinations: list[Destination] | None = None
    scheduled_at: datetime | None = None
    status: Literal["draft", "scheduled", "cancelled"] | None = None


class PublishResultEntry(BaseModel):
    platform: str
    target_urn: str
    target_name: str | None = None
    platform_post_id: str | None = None
    post_url: str | None = None
    published_at: datetime | None = None
    error: str | None = None


class PostPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    org_id: UUID
    created_by: UUID | None = None
    creator_name: str | None = None
    destinations: list[Destination]
    body: str
    title: str | None = None
    status: str
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    publish_result: list[PublishResultEntry] = Field(default_factory=list)
    last_error: str | None = None
    retry_count: int
    media: list[MediaPublic] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ---- LinkedIn account discovery -------------------------------------


class LinkedInAccount(BaseModel):
    """A destination the user can pick when composing a post. Derived from
    their configured LinkedIn integration + (later) organization access."""
    target_type: Literal["person", "organization"]
    target_urn: str
    target_name: str


# ---- Calendar / list response wrappers -----------------------------


class PostsSummary(BaseModel):
    total: int = 0
    drafts: int = 0
    scheduled: int = 0
    published_30d: int = 0
    failed: int = 0
    impressions_30d: int = 0
    engagements_30d: int = 0


class PostMediaUploadResult(BaseModel):
    ok: bool
    media_id: UUID
    url: str
    filename: str
    size_bytes: int


class PublishNowResult(BaseModel):
    ok: bool
    post_id: UUID
    detail: str
    results: list[PublishResultEntry] = Field(default_factory=list)
