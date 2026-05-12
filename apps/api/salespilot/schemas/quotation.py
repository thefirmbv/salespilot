"""Pydantic schemas for Quotations."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class QuotationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    deal_id: UUID | None = None
    halopsa_id: int
    reference: str | None = None
    subject: str | None = None
    status: str
    status_label_halopsa: str | None = None
    amount_net: Decimal | None = None
    amount_gross: Decimal | None = None
    currency: str = "EUR"
    sent_at: datetime | None = None
    valid_until: datetime | None = None
    accepted_at: datetime | None = None
    rejected_at: datetime | None = None
    synced_at: datetime
    created_at: datetime
    updated_at: datetime
    # Optional joined fields the API may add for convenience.
    company_name: str | None = None
    deal_name: str | None = None


class QuotationSummary(BaseModel):
    """KPI block summary for the dashboard."""

    open_count: int = 0
    open_amount: Decimal = Decimal("0")
    expiring_soon_count: int = 0  # 14-30 days since sent, status=sent
    expired_count: int = 0
    accepted_count_30d: int = 0
    accepted_amount_30d: Decimal = Decimal("0")
    rejected_count_30d: int = 0
    hit_rate_90d: float = 0.0  # accepted / (accepted + rejected) over 90 days
    currency: str = "EUR"


class QuotationSyncResult(BaseModel):
    ok: bool
    detail: str
    fetched: int = 0
    created: int = 0
    updated: int = 0
    deals_created: int = 0
    reminders_scheduled: int = 0
