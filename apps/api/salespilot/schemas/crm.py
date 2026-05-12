"""CRM object schemas — Contact, Company, Deal, Activity."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

JsonDict = Annotated[dict, Field(default_factory=dict)]


# --- Company ---

class CompanyBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    domain: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=120)
    size: str | None = Field(default=None, max_length=40)
    description: str | None = None
    custom: JsonDict


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    domain: str | None = None
    industry: str | None = None
    size: str | None = None
    description: str | None = None
    custom: dict | None = None


class CompanyPublic(CompanyBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source: str
    halopsa_id: int | None = None
    halopsa_synced_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# --- Contact ---

class ContactBase(BaseModel):
    email: EmailStr | None = None
    first_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=40)
    job_title: str | None = Field(default=None, max_length=120)
    company_id: UUID | None = None
    owner_id: UUID | None = None
    custom: JsonDict


class ContactCreate(ContactBase):
    pass


class ContactUpdate(BaseModel):
    email: EmailStr | None = None
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    job_title: str | None = None
    company_id: UUID | None = None
    owner_id: UUID | None = None
    custom: dict | None = None


class ContactPublic(ContactBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime
    updated_at: datetime


# --- Deal ---

class DealBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    amount: float | None = None
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    pipeline_id: UUID
    stage_id: UUID
    company_id: UUID | None = None
    primary_contact_id: UUID | None = None
    owner_id: UUID | None = None
    expected_close_date: datetime | None = None
    custom: JsonDict


class DealCreate(DealBase):
    pass


class DealUpdate(BaseModel):
    name: str | None = None
    amount: float | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    stage_id: UUID | None = None
    status: str | None = None  # "open" | "won" | "lost"
    company_id: UUID | None = None
    primary_contact_id: UUID | None = None
    owner_id: UUID | None = None
    expected_close_date: datetime | None = None
    custom: dict | None = None


class DealPublic(DealBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


# --- Activity ---

class ActivityBase(BaseModel):
    type: str  # note | call | email | meeting | task
    target_type: str  # contact | company | deal
    target_id: UUID
    subject: str | None = Field(default=None, max_length=200)
    body: str | None = None
    due_at: datetime | None = None
    completed_at: datetime | None = None


class ActivityCreate(ActivityBase):
    pass


class ActivityUpdate(BaseModel):
    subject: str | None = None
    body: str | None = None
    due_at: datetime | None = None
    completed_at: datetime | None = None


class ActivityPublic(ActivityBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    author_id: UUID | None
    created_at: datetime
    updated_at: datetime


# --- Paginated list envelope ---

class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
