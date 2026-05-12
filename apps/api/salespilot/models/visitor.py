"""Visitor / tracking events (ProspectPRO, Leadinfo, etc.)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from salespilot.models import Base, TenantScoped, Timestamps, UUIDPrimaryKey


class VisitorEvent(UUIDPrimaryKey, TenantScoped, Base):
    """A single tracked event for a visitor on our website.

    Source is the tracker that observed it (`prospectpro`, `leadinfo`, ...).
    company_id is set when we can resolve the visiting domain to a company
    in our database; otherwise null and we keep the raw payload for later
    matching.
    """

    __tablename__ = "visitor_events"

    company_id: Mapped[UUID | None] = mapped_column()
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(120))
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    page_title: Mapped[str | None] = mapped_column(Text)
    referrer: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
