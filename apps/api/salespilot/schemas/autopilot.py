"""Pydantic schemas for sequences, enrollments, messages, LinkedIn tasks."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---- Sequences ----


class SendWindow(BaseModel):
    days: list[int] = Field(default_factory=lambda: [1, 2, 3])  # ISO weekday 1=Mon
    hours: list[list[int]] = Field(default_factory=lambda: [[9, 11], [14, 16]])
    tz: str = "Europe/Amsterdam"


class SequenceBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    status: str = "draft"  # draft | active | paused | archived
    auto_enroll_bucket: str | None = None  # hot | warm | cold | null
    auto_enroll_min_score: int | None = None
    auto_enroll_max_score: int | None = None
    from_name: str = "Sales"
    from_email: str
    reply_to_email: str | None = None
    daily_limit: int = 25
    send_window_json: SendWindow = Field(default_factory=SendWindow)
    cooldown_hours: int = 48
    stop_on_reply: bool = True


class SequenceCreate(SequenceBase):
    pass


class SequenceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    auto_enroll_bucket: str | None = None
    auto_enroll_min_score: int | None = None
    auto_enroll_max_score: int | None = None
    from_name: str | None = None
    from_email: str | None = None
    reply_to_email: str | None = None
    daily_limit: int | None = None
    send_window_json: SendWindow | None = None
    cooldown_hours: int | None = None
    stop_on_reply: bool | None = None


class SequencePublic(SequenceBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime
    updated_at: datetime
    # Computed counts that the API will tack on. Optional in case the
    # endpoint that returns this is a generic list endpoint.
    enrollments_active: int = 0
    enrollments_replied: int = 0


# ---- Sequence steps ----


class SequenceStepBase(BaseModel):
    position: int = Field(ge=0)
    kind: str  # email | linkedin_connect | linkedin_dm | linkedin_like | linkedin_visit
    wait_days: int = 0
    template_subject: str | None = None
    template_body: str | None = None
    reply_in_thread: bool = False


class SequenceStepCreate(SequenceStepBase):
    pass


class SequenceStepUpdate(BaseModel):
    position: int | None = None
    kind: str | None = None
    wait_days: int | None = None
    template_subject: str | None = None
    template_body: str | None = None
    reply_in_thread: bool | None = None


class SequenceStepPublic(SequenceStepBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sequence_id: UUID
    created_at: datetime
    updated_at: datetime


# ---- Enrollments ----


class EnrollmentCreate(BaseModel):
    sequence_id: UUID
    company_id: UUID
    contact_id: UUID | None = None


class EnrollmentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sequence_id: UUID
    company_id: UUID
    contact_id: UUID | None
    status: str
    current_step_position: int
    score_at_enroll: int | None
    bucket_at_enroll: str | None
    next_action_at: datetime | None
    last_action_at: datetime | None
    enrolled_at: datetime
    stopped_at: datetime | None
    stopped_reason: str | None
    created_at: datetime
    updated_at: datetime


# ---- Messages ----


class MessagePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enrollment_id: UUID
    step_id: UUID
    channel: str
    status: str
    subject: str | None
    to_email: str | None
    from_email: str | None
    sent_at: datetime | None
    opened_at: datetime | None
    replied_at: datetime | None
    error: str | None
    created_at: datetime


# ---- LinkedIn tasks ----


class LinkedInTaskBase(BaseModel):
    company_id: UUID
    contact_id: UUID | None = None
    kind: str  # linkedin_connect | linkedin_dm | linkedin_like | linkedin_visit
    suggested_text: str | None = None
    profile_url: str | None = None
    post_url: str | None = None
    scheduled_for: datetime | None = None
    notes: str | None = None


class LinkedInTaskCreate(LinkedInTaskBase):
    pass


class LinkedInTaskUpdate(BaseModel):
    status: str | None = None
    suggested_text: str | None = None
    profile_url: str | None = None
    post_url: str | None = None
    notes: str | None = None


class LinkedInTaskPublic(LinkedInTaskBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enrollment_id: UUID | None
    step_id: UUID | None
    status: str
    sent_at: datetime | None
    replied_at: datetime | None
    created_at: datetime
    updated_at: datetime


# ---- LinkedIn posts ----


class LinkedInPostBase(BaseModel):
    body: str = Field(min_length=1)
    media_urls_json: list[str] = Field(default_factory=list)
    audience: str = "PUBLIC"
    scheduled_for: datetime | None = None


class LinkedInPostCreate(LinkedInPostBase):
    pass


class LinkedInPostUpdate(BaseModel):
    body: str | None = None
    media_urls_json: list[str] | None = None
    audience: str | None = None
    scheduled_for: datetime | None = None
    status: str | None = None


class LinkedInPostPublic(LinkedInPostBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    posted_at: datetime | None
    status: str
    external_id: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime


# ---- Integration configs ----


class MailgunConfig(BaseModel):
    base_url: str = "api.eu.mailgun.net"  # 'api.eu.mailgun.net' or 'api.mailgun.net'
    domain: str  # 'mail.it-gemak.nl'
    api_key: str = Field(min_length=1)
    webhook_signing_key: str | None = None


class LinkedInConfig(BaseModel):
    """OAuth2 LinkedIn integration. Filled in via OAuth callback."""

    client_id: str
    client_secret: str
    access_token: str | None = None
    refresh_token: str | None = None
    expires_at: datetime | None = None
    person_urn: str | None = None
    organization_urn: str | None = None


# ---- Stats for the sequences overview header ----


class SequenceStats(BaseModel):
    active_enrollments: int
    sent_last_7d: int
    replied_last_7d: int
    reply_rate: float
    queue_today: int
    next_send_at: datetime | None
