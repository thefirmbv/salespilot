"""Pydantic schemas for HaloPSA mail campaigns."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MailCampaignPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    halopsa_id: int
    name: str
    subject: str | None = None
    from_name: str | None = None
    from_email: str | None = None
    status: str
    status_label_halopsa: str | None = None
    sent_at: datetime | None = None
    scheduled_at: datetime | None = None
    recipients_total: int
    sent_count: int
    delivered_count: int
    opened_count: int
    clicked_count: int
    bounced_count: int
    unsubscribed_count: int
    complained_count: int
    # Convenience-percentages (delivered = denominator since opens off undelivered are
    # not measurable).
    open_rate: float = 0.0
    click_rate: float = 0.0
    bounce_rate: float = 0.0
    synced_at: datetime
    created_at: datetime
    updated_at: datetime


class MailCampaignRecipientPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    campaign_id: UUID
    company_id: UUID | None = None
    company_name: str | None = None
    contact_id: UUID | None = None
    contact_name: str | None = None
    email: str
    name: str | None = None
    status: str
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    opened_at: datetime | None = None
    clicked_at: datetime | None = None
    bounced_at: datetime | None = None
    unsubscribed_at: datetime | None = None
    open_count: int
    click_count: int
    created_at: datetime


class MailCampaignsSummary(BaseModel):
    total_campaigns: int = 0
    campaigns_last_30d: int = 0
    recipients_total_30d: int = 0
    delivered_30d: int = 0
    opened_30d: int = 0
    clicked_30d: int = 0
    bounced_30d: int = 0
    avg_open_rate_30d: float = 0.0
    avg_click_rate_30d: float = 0.0
    avg_bounce_rate_30d: float = 0.0


class MailCampaignSyncResult(BaseModel):
    ok: bool
    detail: str
    fetched: int = 0
    created: int = 0
    updated: int = 0
    recipients_synced: int = 0
