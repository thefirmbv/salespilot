"""Pydantic schemas for the Wespennest acquisition pipeline."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


# ----- MSP -----

class MspBase(BaseModel):
    name: str
    kvk_number: str | None = None
    website: str | None = None
    acquired_by: str | None = None
    acquired_date: date | None = None
    investor: str | None = None
    region: str | None = None
    source_url: str | None = None
    notes: str | None = None


class MspCreate(MspBase):
    pass


class MspUpdate(BaseModel):
    name: str | None = None
    kvk_number: str | None = None
    website: str | None = None
    acquired_by: str | None = None
    acquired_date: date | None = None
    investor: str | None = None
    region: str | None = None
    source_url: str | None = None
    notes: str | None = None
    is_active: bool | None = None


class MspPublic(MspBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime
    # Derived / joined
    domain_count: int = 0
    lead_count: int = 0
    fingerprint_count: int = 0


# ----- Lead -----

class LeadPublic(BaseModel):
    """A qualified lead = one row of the lead_candidates join.

    This is the bell-list view: KVK company + decision-maker + MSP attribution
    + the M365 + distance signals required to filter.
    """
    model_config = ConfigDict(from_attributes=True)

    # KVK side
    kvk_company_id: UUID
    kvk_nummer: str
    handelsnaam: str
    rechtsvorm: str | None = None
    werkzame_personen: int | None = None
    plaats: str | None = None
    postcode: str | None = None
    km_to_hq: float | None = None
    telefoon_bedrijf: str | None = None

    # Domain side
    domain_id: UUID | None = None
    domain: str | None = None
    has_m365: bool | None = None
    m365_tier_hint: str | None = None

    # MSP attribution
    msp_id: UUID | None = None
    msp_name: str | None = None
    msp_acquired_by: str | None = None
    msp_acquired_date: date | None = None
    msp_confidence: int | None = None

    # Decision maker
    decision_maker_id: UUID | None = None
    contact_naam: str | None = None
    contact_functie: str | None = None
    contact_email: str | None = None
    contact_email_verified: str | None = None
    contact_telefoon: str | None = None

    # Outreach state — is this lead already in a sequence?
    existing_contact_id: UUID | None = None
    in_sequence: bool = False


class LeadsSummary(BaseModel):
    total_msps: int = 0
    msps_with_acquisition: int = 0
    total_domains: int = 0
    domains_with_m365: int = 0
    qualified_leads: int = 0
    qualified_with_decision_maker: int = 0
    qualified_within_40km: int = 0
    qualified_msps_with_recent_acquisition: int = 0
    avg_km_to_hq: float = 0.0


# ----- Acquisition feed -----

class AcquisitionSignalBase(BaseModel):
    source: str
    source_url: str
    title: str
    excerpt: str | None = None
    published_at: datetime | None = None


class AcquisitionSignalCreate(AcquisitionSignalBase):
    matched_keywords: list[str] | None = None


class AcquisitionSignalUpdate(BaseModel):
    status: str | None = None
    msp_id: UUID | None = None
    notes: str | None = None


class AcquisitionSignalPublic(AcquisitionSignalBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str
    matched_keywords: list[str] | None = None
    msp_id: UUID | None = None
    msp_name: str | None = None
    reviewer_id: UUID | None = None
    reviewed_at: datetime | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


# ----- Pipeline runs -----

class PipelineRunPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    job_kind: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    items_processed: int
    items_created: int
    items_failed: int
    message: str | None = None
    duration_seconds: float | None = None


class PipelineStatusSummary(BaseModel):
    """Single roll-up: for each known job_kind, the latest run + counters."""
    jobs: dict[str, PipelineRunPublic | None] = {}


class PipelineTriggerResult(BaseModel):
    ok: bool
    detail: str
    job_kind: str
    run_id: UUID | None = None
