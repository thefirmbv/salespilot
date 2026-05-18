"""Employees + asset inventory.

Houdt eigen medewerkers + uitgegeven assets bij (auto/telefoon/laptop/
overig). Type-specifieke velden zitten in JSONB `details` zodat we niet
voor elk asset-type een eigen kolommen-set hoeven onderhouden.

Standaard tenant-scoped via RLS (migration 0021).
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    Date, DateTime, ForeignKey, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship


# Base wordt geïmporteerd via __init__ van models
from salespilot.models import Base


class Employee(Base):
    __tablename__ = "employees"
    __table_args__ = (
        UniqueConstraint("org_id", "email", name="uq_employees_org_email"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(40))
    role: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    nmbrs_employee_id: Mapped[str | None] = mapped_column(String(40))
    nmbrs_company_id: Mapped[str | None] = mapped_column(String(40))
    halopsa_agent_id: Mapped[int | None] = mapped_column()
    halopsa_agent_name: Mapped[str | None] = mapped_column(String(160))
    started_at: Mapped[date | None] = mapped_column(Date)
    ended_at: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    assets: Mapped[list["EmployeeAsset"]] = relationship(
        "EmployeeAsset", back_populates="employee", cascade="all, delete-orphan",
    )


class EmployeeAsset(Base):
    __tablename__ = "employee_assets"

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
    asset_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # 'vehicle' | 'phone' | 'laptop' | 'other'
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    identifier: Mapped[str | None] = mapped_column(String(120))
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    assigned_at: Mapped[date | None] = mapped_column(Date)
    returned_at: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    employee: Mapped["Employee"] = relationship("Employee", back_populates="assets")
