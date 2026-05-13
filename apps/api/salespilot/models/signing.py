"""Public-facing signed SEPA direct-debit mandates.

Lives on sign.it-gemak.nl. Submissions come from non-authenticated
visitors, so the row is NOT tenant-scoped via RLS — instead it is
hard-pinned to the IT-gemak org_id at insertion time (read from settings).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from salespilot.models import Base


class SignedMandate(Base):
    __tablename__ = "signed_mandates"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    umr: Mapped[str] = mapped_column(String(35), nullable=False, unique=True)

    # Debiteur
    debtor_name: Mapped[str] = mapped_column(String(200), nullable=False)
    debtor_address: Mapped[str] = mapped_column(String(255), nullable=False)
    debtor_postcode: Mapped[str] = mapped_column(String(20), nullable=False)
    debtor_city: Mapped[str] = mapped_column(String(120), nullable=False)
    debtor_country: Mapped[str] = mapped_column(String(80), nullable=False, default="Nederland")
    debtor_iban: Mapped[str] = mapped_column(String(34), nullable=False)
    debtor_bic: Mapped[str | None] = mapped_column(String(11))
    debtor_email: Mapped[str] = mapped_column(String(255), nullable=False)
    debtor_phone: Mapped[str | None] = mapped_column(String(40))
    debtor_kvk: Mapped[str | None] = mapped_column(String(20))

    # Signature
    sign_place: Mapped[str] = mapped_column(String(120), nullable=False)
    signature_png_base64: Mapped[str] = mapped_column(Text, nullable=False)

    # Audit trail
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)
    geo_country: Mapped[str | None] = mapped_column(String(80))
    geo_region: Mapped[str | None] = mapped_column(String(80))
    geo_city: Mapped[str | None] = mapped_column(String(120))
    geo_lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    geo_lon: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))

    # KvK verification
    kvk_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    kvk_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kvk_raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # Integrity
    pdf_path: Mapped[str | None] = mapped_column(String(500))
    pdf_sha256: Mapped[str | None] = mapped_column(String(64))

    # Workflow
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="submitted")
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_error: Mapped[str | None] = mapped_column(Text)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"),
    )
