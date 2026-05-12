"""Wespennest models — acquisition-target pipeline for clients of acquired MSPs.

See `alembic/versions/0008_wespennest.py` for the migration that creates
these tables, plus high-level architecture documentation.
"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from salespilot.models import Base, TenantScoped, Timestamps, UUIDPrimaryKey


class WnMsp(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    __tablename__ = "wn_msps"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kvk_number: Mapped[str | None] = mapped_column(String(8))
    website: Mapped[str | None] = mapped_column(String(200))
    acquired_by: Mapped[str | None] = mapped_column(String(200))
    acquired_date: Mapped[date | None] = mapped_column(Date)
    investor: Mapped[str | None] = mapped_column(String(200))
    region: Mapped[str | None] = mapped_column(String(120))
    source_url: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class WnMspFingerprint(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    __tablename__ = "wn_msp_fingerprints"

    msp_id: Mapped[UUID] = mapped_column(nullable=False)
    signal_type: Mapped[str] = mapped_column(String(40), nullable=False)
    pattern: Mapped[str] = mapped_column(String(500), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class WnDomain(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    __tablename__ = "wn_domains"

    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    discovery_source: Mapped[str | None] = mapped_column(String(40))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_scanned: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)


class WnDomainSignals(UUIDPrimaryKey, TenantScoped, Base):
    """Per-domain scan results. Not Timestamps-mixin because scanned_at
    is the authoritative time on this row."""

    __tablename__ = "wn_domain_signals"

    domain_id: Mapped[UUID] = mapped_column(nullable=False)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dns: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    m365: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    mail: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    web: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class WnVendorAttribution(UUIDPrimaryKey, TenantScoped, Base):
    __tablename__ = "wn_vendor_attribution"

    domain_id: Mapped[UUID] = mapped_column(nullable=False)
    msp_id: Mapped[UUID] = mapped_column(nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    rules_fired: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    attributed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WnKvkCompany(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    __tablename__ = "wn_kvk_companies"

    kvk_nummer: Mapped[str] = mapped_column(String(8), nullable=False)
    handelsnaam: Mapped[str | None] = mapped_column(String(300))
    rechtsvorm: Mapped[str | None] = mapped_column(String(80))
    sbi_codes: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    werkzame_personen: Mapped[int | None] = mapped_column(Integer)
    grootteklasse: Mapped[str | None] = mapped_column(String(8))
    adres: Mapped[str | None] = mapped_column(String(300))
    postcode: Mapped[str | None] = mapped_column(String(8))
    plaats: Mapped[str | None] = mapped_column(String(120))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    km_to_hq: Mapped[float | None] = mapped_column(Float)
    telefoon: Mapped[str | None] = mapped_column(String(40))
    nis2_sector: Mapped[str | None] = mapped_column(String(80))
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WnDomainKvk(TenantScoped, Base):
    """Composite-key link table. Not UUIDPrimaryKey because the PK is
    (org_id, domain_id, kvk_company_id)."""

    __tablename__ = "wn_domain_kvk"

    domain_id: Mapped[UUID] = mapped_column(primary_key=True, nullable=False)
    kvk_company_id: Mapped[UUID] = mapped_column(primary_key=True, nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WnDecisionMaker(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    __tablename__ = "wn_decision_makers"

    kvk_company_id: Mapped[UUID] = mapped_column(nullable=False)
    voornaam: Mapped[str | None] = mapped_column(String(120))
    tussenvoegsel: Mapped[str | None] = mapped_column(String(40))
    achternaam: Mapped[str | None] = mapped_column(String(120))
    functie: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(255))
    email_verified: Mapped[str] = mapped_column(String(20), default="unverified", nullable=False)
    email_verify_method: Mapped[str | None] = mapped_column(String(40))
    email_pattern_used: Mapped[str | None] = mapped_column(String(80))
    telefoon: Mapped[str | None] = mapped_column(String(40))
    linkedin_url: Mapped[str | None] = mapped_column(String(300))
    source: Mapped[str | None] = mapped_column(String(40))
    contact_id: Mapped[UUID | None] = mapped_column()


class WnAcquisitionSignal(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    __tablename__ = "wn_acquisition_signals"

    source: Mapped[str] = mapped_column(String(40), nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="new", nullable=False)
    matched_keywords: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    msp_id: Mapped[UUID | None] = mapped_column()
    reviewer_id: Mapped[UUID | None] = mapped_column()
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class WnPipelineRun(UUIDPrimaryKey, TenantScoped, Base):
    __tablename__ = "wn_pipeline_runs"

    job_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    items_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
