"""Personal calendar — events, recurrence templates, reflections.

A per-user agenda lives in SalesPilot. Each user owns their own events.
Privacy by design: events are USER-scoped (not org-shared) so colleagues
can't see each other's calendar.

Three concepts:
  * calendar_events       -- concrete occurrences with a start/end + type
  * recurrence_templates  -- "elke dinsdag 9:00-9:30 standup"; spawns
                             events for upcoming weeks
  * event_reflections     -- a 1-emoji ('green'/'yellow'/'red') +
                             optional note logged after the block

Revision ID: 0013_personal_calendar
Revises: 0012_signed_mandates
Create Date: 2026-05-13
"""

from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "0013_personal_calendar"
down_revision: Union[str, None] = "0012_signed_mandates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "calendar_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recurrence_template_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),

        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False, server_default="other"),
        sa.Column("color_hex", sa.String(7), nullable=True),

        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("all_day", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("location", sa.String(200), nullable=True),

        sa.Column("outlook_event_id", sa.String(200), nullable=True),
        sa.Column("outlook_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outlook_sync_error", sa.Text(), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_calendar_events_user_start",
                    "calendar_events", ["user_id", "start_at"])

    op.create_table(
        "recurrence_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),

        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False, server_default="other"),
        sa.Column("color_hex", sa.String(7), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("location", sa.String(200), nullable=True),

        sa.Column("weekdays_bitmask", sa.SmallInteger(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),

        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),

        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "event_reflections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("calendar_events.id", ondelete="CASCADE"),
                  nullable=False, unique=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("outcome", sa.String(10), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade() -> None:
    op.drop_table("event_reflections")
    op.drop_table("recurrence_templates")
    op.drop_index("ix_calendar_events_user_start", table_name="calendar_events")
    op.drop_table("calendar_events")
