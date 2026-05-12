"""Sequences, enrollments, messages, LinkedIn tasks, mail suppression.

Revision ID: 0004_autopilot
Revises: 0003_prospects
Create Date: 2026-05-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_autopilot"
down_revision: Union[str, None] = "0003_prospects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Mailgun + LinkedIn need their own integration kinds (already supported by
    # the generic integrations table — no schema change for the table itself).

    # Sequences = one campaign. Score-bucket auto-enrolment is optional;
    # `auto_enroll_bucket` may be NULL for manual-only sequences.
    op.create_table(
        "sequences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("auto_enroll_bucket", sa.String(10), nullable=True),  # hot|warm|cold
        sa.Column("auto_enroll_min_score", sa.Integer(), nullable=True),
        sa.Column("auto_enroll_max_score", sa.Integer(), nullable=True),
        sa.Column("from_name", sa.String(120), nullable=False, server_default="Sales"),
        sa.Column("from_email", sa.String(200), nullable=False),
        sa.Column("reply_to_email", sa.String(200), nullable=True),
        sa.Column("daily_limit", sa.Integer(), nullable=False, server_default="25"),
        sa.Column(
            "send_window_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text(
                "'{\"days\": [1,2,3], \"hours\": [[9,11],[14,16]], \"tz\": \"Europe/Amsterdam\"}'::jsonb"
            ),
        ),
        sa.Column("cooldown_hours", sa.Integer(), nullable=False, server_default="48"),
        sa.Column("stop_on_reply", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_sequences_org_status", "sequences", ["org_id", "status"])

    # Steps inside a sequence. Order within a sequence is `position`.
    op.create_table(
        "sequence_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),  # email | linkedin_connect | linkedin_dm | linkedin_like
        sa.Column("wait_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("template_subject", sa.Text(), nullable=True),
        sa.Column("template_body", sa.Text(), nullable=True),
        sa.Column("reply_in_thread", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sequence_id"], ["sequences.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_sequence_steps_seq_pos",
        "sequence_steps",
        ["sequence_id", "position"],
        unique=True,
    )

    # Enrollments = one prospect in one sequence.
    op.create_table(
        "enrollments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        # active | paused | replied | stopped | done | bounced
        sa.Column("current_step_position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score_at_enroll", sa.Integer(), nullable=True),
        sa.Column("bucket_at_enroll", sa.String(10), nullable=True),
        sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_action_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_reason", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sequence_id"], ["sequences.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_enrollments_due",
        "enrollments",
        ["org_id", "status", "next_action_at"],
    )
    op.create_index(
        "ix_enrollments_seq_company",
        "enrollments",
        ["sequence_id", "company_id"],
        unique=True,
    )

    # Outbound mail/LinkedIn messages — one per send attempt.
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("enrollment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),  # email | linkedin
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        # queued | sent | opened | replied | bounced | failed | unsubscribed
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("to_email", sa.String(200), nullable=True),
        sa.Column("from_email", sa.String(200), nullable=True),
        sa.Column("external_id", sa.String(200), nullable=True),  # mailgun message-id
        sa.Column("thread_message_id", sa.String(200), nullable=True),  # for in-thread replies
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["enrollment_id"], ["enrollments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["step_id"], ["sequence_steps.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_messages_external_id", "messages", ["external_id"])
    op.create_index("ix_messages_enrollment", "messages", ["enrollment_id", "created_at"])

    # LinkedIn outreach tasks — queued but not auto-sent.
    op.create_table(
        "linkedin_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("enrollment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("step_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(30), nullable=False),
        # linkedin_connect | linkedin_dm | linkedin_like | linkedin_visit
        sa.Column("status", sa.String(20), nullable=False, server_default="todo"),
        # todo | sent | connected | replied | skipped
        sa.Column("suggested_text", sa.Text(), nullable=True),
        sa.Column("profile_url", sa.Text(), nullable=True),
        sa.Column("post_url", sa.Text(), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["enrollment_id"], ["enrollments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["step_id"], ["sequence_steps.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_linkedin_tasks_org_status",
        "linkedin_tasks",
        ["org_id", "status"],
    )

    # Mail suppression: unsubscribes + permanent bounces. Org-wide.
    op.create_table(
        "mail_suppression",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(200), nullable=False),
        sa.Column("reason", sa.String(40), nullable=False),  # unsubscribe | bounce | complaint | manual
        sa.Column("source_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_mail_suppression_org_email",
        "mail_suppression",
        ["org_id", "email"],
        unique=True,
    )

    # Scheduled LinkedIn posts (for the future post-scheduling feature).
    op.create_table(
        "linkedin_posts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("media_urls_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("audience", sa.String(20), nullable=False, server_default="PUBLIC"),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        # draft | scheduled | posted | failed
        sa.Column("external_id", sa.String(200), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_linkedin_posts_org_status", "linkedin_posts", ["org_id", "status"])

    # RLS + grants.
    for tbl in (
        "sequences",
        "sequence_steps",
        "enrollments",
        "messages",
        "linkedin_tasks",
        "mail_suppression",
        "linkedin_posts",
    ):
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {tbl}
            USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
            WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
            """
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tbl} TO salespilot_app")


def downgrade() -> None:
    for tbl in (
        "linkedin_posts",
        "mail_suppression",
        "linkedin_tasks",
        "messages",
        "enrollments",
        "sequence_steps",
        "sequences",
    ):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {tbl}")
        op.drop_table(tbl)
