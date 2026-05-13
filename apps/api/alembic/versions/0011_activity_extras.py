"""Activity assignee + priority + outcome columns.

Adds fields the marketing/sales workflow needs for manual call-follow-ups:
  * assignee_id  -- a colleague the activity is for; nullable so older
                    activities (auto-generated quote-followups) remain valid
  * priority     -- low / normal / high / urgent (default 'normal')
  * phone_override -- direct dial / doorkies number distinct from the
                    company's main switchboard
  * outcome      -- after completion: reached / voicemail / no_answer /
                    not_relevant. NULL while the activity is still open.
  * outcome_notes -- free-text note left by the assignee
  * next_followup_id -- when 'no_answer' triggers an auto-scheduled
                    follow-up, this points to the child activity. Soft
                    FK so deletion of the child doesn't break history.

Revision ID: 0011_activity_extras
Revises: 0010_social_posts
Create Date: 2026-05-13
"""

from typing import Union
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011_activity_extras"
down_revision: Union[str, None] = "0010_social_posts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "activities",
        sa.Column(
            "assignee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_activities_assignee_id", "activities", ["assignee_id"],
    )
    op.add_column(
        "activities",
        sa.Column(
            "priority",
            sa.String(10),
            nullable=False,
            server_default="normal",
        ),
    )
    op.add_column(
        "activities",
        sa.Column("phone_override", sa.String(40), nullable=True),
    )
    op.add_column(
        "activities",
        sa.Column("outcome", sa.String(20), nullable=True),
    )
    op.add_column(
        "activities",
        sa.Column("outcome_notes", sa.Text(), nullable=True),
    )
    op.add_column(
        "activities",
        sa.Column(
            "next_followup_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("activities", "next_followup_id")
    op.drop_column("activities", "outcome_notes")
    op.drop_column("activities", "outcome")
    op.drop_column("activities", "phone_override")
    op.drop_column("activities", "priority")
    op.drop_index("ix_activities_assignee_id", table_name="activities")
    op.drop_column("activities", "assignee_id")
