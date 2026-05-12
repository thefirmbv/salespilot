"""Core CRM objects: Company, Contact, Pipeline, Stage, Deal, Activity.

Custom fields are stored per-row in a JSONB column. Field definitions live
in `custom_field_definitions` so the UI knows what to render. This is the
HubSpot/Pipedrive pattern: schema flexibility without per-tenant tables.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from salespilot.models import Base, TenantScoped, Timestamps, UUIDPrimaryKey


class MailPlatform(StrEnum):
    M365 = "m365"
    GOOGLE = "google"
    OTHER = "other"
    UNKNOWN = "unknown"


class CompanySource(StrEnum):
    SALESPILOT = "salespilot"
    HALOPSA = "halopsa"            # synced FROM HaloPSA, read-only
    HALOPSA_PUSHED = "halopsa_pushed"  # was salespilot, pushed TO HaloPSA


class Company(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    domain: Mapped[str | None] = mapped_column(String(255), index=True)
    industry: Mapped[str | None] = mapped_column(String(120))
    size: Mapped[str | None] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text)
    custom: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    # HaloPSA linkage
    source: Mapped[CompanySource] = mapped_column(
        Enum(CompanySource, name="company_source",
             values_callable=lambda e: [x.value for x in e]),
        default=CompanySource.SALESPILOT, nullable=False,
    )
    halopsa_id: Mapped[int | None] = mapped_column(Integer)
    halopsa_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # ProspectPRO linkage
    prospectpro_id: Mapped[str | None] = mapped_column(String(80))
    prospectpro_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Enrichment
    employees: Mapped[int | None] = mapped_column(Integer)
    city: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(2))
    mail_platform: Mapped[MailPlatform] = mapped_column(
        Enum(MailPlatform, name="mail_platform",
             values_callable=lambda e: [x.value for x in e]),
        default=MailPlatform.UNKNOWN, nullable=False,
    )
    mail_platform_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Lead scoring + visitor metrics
    lead_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_visit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pageview_count_30d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # AI callscript cache
    callscript_json: Mapped[dict | None] = mapped_column(JSONB)
    callscript_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    contacts: Mapped[list["Contact"]] = relationship(back_populates="company")
    deals: Mapped[list["Deal"]] = relationship(back_populates="company")


class Contact(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    __tablename__ = "contacts"

    email: Mapped[str | None] = mapped_column(String(255), index=True)
    first_name: Mapped[str | None] = mapped_column(String(80))
    last_name: Mapped[str | None] = mapped_column(String(80))
    phone: Mapped[str | None] = mapped_column(String(40))
    job_title: Mapped[str | None] = mapped_column(String(120))
    company_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    owner_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    custom: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    company: Mapped[Company | None] = relationship(back_populates="contacts")


class Pipeline(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    __tablename__ = "pipelines"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_pipelines_org_name"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_default: Mapped[bool] = mapped_column(default=False, nullable=False)

    stages: Mapped[list["Stage"]] = relationship(
        back_populates="pipeline",
        cascade="all, delete-orphan",
        order_by="Stage.position",
    )


class Stage(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    __tablename__ = "stages"
    __table_args__ = (
        UniqueConstraint("pipeline_id", "position", name="uq_stages_pipeline_position"),
        CheckConstraint("probability >= 0 AND probability <= 100", name="probability_range"),
    )

    pipeline_id: Mapped[UUID] = mapped_column(
        ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    probability: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    # is_won / is_lost mark terminal stages.
    is_won: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_lost: Mapped[bool] = mapped_column(default=False, nullable=False)

    pipeline: Mapped[Pipeline] = relationship(back_populates="stages")


class DealStatus(StrEnum):
    OPEN = "open"
    WON = "won"
    LOST = "lost"


class Deal(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    __tablename__ = "deals"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    status: Mapped[DealStatus] = mapped_column(
        Enum(DealStatus, name="deal_status", values_callable=lambda e: [x.value for x in e]), default=DealStatus.OPEN, nullable=False
    )
    pipeline_id: Mapped[UUID] = mapped_column(
        ForeignKey("pipelines.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    stage_id: Mapped[UUID] = mapped_column(
        ForeignKey("stages.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    company_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    primary_contact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), index=True
    )
    owner_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    expected_close_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    custom: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    company: Mapped[Company | None] = relationship(back_populates="deals")


class ActivityType(StrEnum):
    NOTE = "note"
    CALL = "call"
    EMAIL = "email"
    MEETING = "meeting"
    TASK = "task"


class ActivityTarget(StrEnum):
    CONTACT = "contact"
    COMPANY = "company"
    DEAL = "deal"


class Activity(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    """Polymorphic activity attached to one of: contact, company, deal.

    We keep target_type + target_id rather than three nullable FKs because
    queries like "show me all activities for this deal" stay simple, and
    the polymorphism is naturally enforced at the application layer.
    """

    __tablename__ = "activities"

    type: Mapped[ActivityType] = mapped_column(
        Enum(ActivityType, name="activity_type", values_callable=lambda e: [x.value for x in e]), nullable=False, index=True
    )
    target_type: Mapped[ActivityTarget] = mapped_column(
        Enum(ActivityTarget, name="activity_target", values_callable=lambda e: [x.value for x in e]), nullable=False
    )
    target_id: Mapped[UUID] = mapped_column(nullable=False, index=True)

    subject: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    author_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Link back to a quotation if this activity is a follow-up reminder.
    quotation_id: Mapped[UUID | None] = mapped_column()
    # Marks the kind of automatic reminder, e.g. 'quote_followup_14d' or
    # 'quote_followup_28d'. Null for manually-created activities.
    reminder_kind: Mapped[str | None] = mapped_column(String(40))


class CustomFieldType(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    SELECT = "select"
    MULTISELECT = "multiselect"


class CustomFieldDefinition(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    """User-defined fields. Used to validate the `custom` JSONB on each entity."""

    __tablename__ = "custom_field_definitions"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "object_type", "key", name="uq_cfd_org_object_key"
        ),
    )

    # Which entity this field applies to: 'contact', 'company', 'deal'.
    object_type: Mapped[str] = mapped_column(String(20), nullable=False)
    key: Mapped[str] = mapped_column(String(60), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[CustomFieldType] = mapped_column(
        Enum(CustomFieldType, name="custom_field_type", values_callable=lambda e: [x.value for x in e]), nullable=False
    )
    # For select/multiselect: JSON list of strings.
    options: Mapped[list[str] | None] = mapped_column(JSON)
    required: Mapped[bool] = mapped_column(default=False, nullable=False)
