"""Personal calendar models -- per-user, NOT tenant-scoped via RLS.

Privacy: events are owned by a single user and queried by user_id;
no other colleague (even within the same org) can see them. The
calendar API enforces auth.user_id == row.user_id on every read/write.
"""

from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, SmallInteger, String, Text, Time, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from salespilot.models import Base


class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    recurrence_template_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), index=True,
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    # focus | client | admin | break | meeting | personal | other
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="other")
    color_hex: Mapped[str | None] = mapped_column(String(7))

    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    all_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    location: Mapped[str | None] = mapped_column(String(200))

    outlook_event_id: Mapped[str | None] = mapped_column(String(200))
    outlook_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outlook_sync_error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"),
    )


class RecurrenceTemplate(Base):
    __tablename__ = "recurrence_templates"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="other")
    color_hex: Mapped[str | None] = mapped_column(String(7))
    notes: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(200))

    # weekdays bitmask: Mon=1, Tue=2, Wed=4, Thu=8, Fri=16, Sat=32, Sun=64
    weekdays_bitmask: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"),
    )


class EventReflection(Base):
    __tablename__ = "event_reflections"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("calendar_events.id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # green | yellow | red
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"),
    )
