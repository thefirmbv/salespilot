"""HaloPSA quotations + their lifecycle in SalesPilot.

A Quotation is sourced from HaloPSA — never created in SalesPilot directly.
We keep enough denormalised fields that the UI can render lists + filters
without re-fetching from HaloPSA, but the raw payload is also stored.

Status mapping rules live in `integrations.halopsa_quotations` so changes
to HaloPSA's status taxonomy don't ripple into the model layer.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from salespilot.models import Base, TenantScoped, Timestamps, UUIDPrimaryKey


class Quotation(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    __tablename__ = "quotations"

    company_id: Mapped[UUID] = mapped_column(nullable=False)
    deal_id: Mapped[UUID | None] = mapped_column()
    halopsa_id: Mapped[int] = mapped_column(Integer, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(80))
    subject: Mapped[str | None] = mapped_column(Text)
    # 'draft' | 'sent' | 'accepted' | 'rejected' | 'expired'
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    status_id_halopsa: Mapped[int | None] = mapped_column(Integer)
    status_label_halopsa: Mapped[str | None] = mapped_column(String(80))
    amount_net: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    amount_gross: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
