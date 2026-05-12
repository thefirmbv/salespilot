"""HaloPSA mail campaigns imported via /api/MailCampaign.

A campaign is one outbound marketing send (newsletter, announcement, etc.)
composed in HaloPSA. We import metadata + per-recipient engagement events
so we can see in SalesPilot which clients received which campaigns and
how they reacted.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from salespilot.models import Base, TenantScoped, Timestamps, UUIDPrimaryKey


class MailCampaign(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    __tablename__ = "mail_campaigns"

    halopsa_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    subject: Mapped[str | None] = mapped_column(Text)
    from_name: Mapped[str | None] = mapped_column(String(120))
    from_email: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    status_label_halopsa: Mapped[str | None] = mapped_column(String(80))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recipients_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    delivered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    opened_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    clicked_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bounced_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unsubscribed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    complained_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MailCampaignRecipient(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    """One row per (campaign × recipient). Engagement events are stored
    inline because we don't need a separate events table — HaloPSA gives
    us aggregated state per recipient anyway."""

    __tablename__ = "mail_campaign_recipients"

    campaign_id: Mapped[UUID] = mapped_column(nullable=False)
    company_id: Mapped[UUID | None] = mapped_column()
    contact_id: Mapped[UUID | None] = mapped_column()
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bounced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    open_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    click_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    halopsa_recipient_id: Mapped[int | None] = mapped_column(Integer)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
