"""Synced absences model voor NMBRS -> HaloPSA verlof-doorpush.

Houdt bij welke NMBRS-absence-records we al naar HaloPSA hebben
gepusht, met halopsa_appointment_id voor idempotent updates.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from salespilot.models import Base


class SyncedAbsence(Base):
    __tablename__ = "synced_absences"
    __table_args__ = (
        UniqueConstraint("org_id", "source", "business_key",
                         name="uq_synced_absences_org_business"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    employee_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    nmbrs_absence_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    business_key: Mapped[str | None] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="absence")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    nmbrs_company_id: Mapped[str | None] = mapped_column(String(40))
    halopsa_appointment_id: Mapped[int | None] = mapped_column(Integer)
    absence_type_code: Mapped[str | None] = mapped_column(String(20))
    absence_type_label: Mapped[str | None] = mapped_column(String(120))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    percentage: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(String(255))
    last_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
