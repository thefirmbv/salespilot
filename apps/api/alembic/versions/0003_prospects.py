"""Lead scoring + visitor events + Anthropic integration kind.

Revision ID: 0003_prospects
Revises: 0002_halopsa
Create Date: 2026-05-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_prospects"
down_revision: Union[str, None] = "0002_halopsa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enum for detected mail platform.
    op.execute(
        "CREATE TYPE mail_platform AS ENUM "
        "('m365', 'google', 'other', 'unknown')"
    )

    # Add scoring + visitor + mail-platform columns to companies.
    op.add_column(
        "companies",
        sa.Column("lead_score", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "companies",
        sa.Column(
            "mail_platform",
            postgresql.ENUM(
                "m365", "google", "other", "unknown",
                name="mail_platform", create_type=False,
            ),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "companies",
        sa.Column("mail_platform_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "companies",
        sa.Column("last_visit_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "companies",
        sa.Column(
            "pageview_count_30d", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "companies",
        sa.Column("employees", sa.Integer(), nullable=True),
    )
    op.add_column(
        "companies",
        sa.Column("city", sa.String(120), nullable=True),
    )
    op.add_column(
        "companies",
        sa.Column("country", sa.String(2), nullable=True),
    )
    # ProspectPRO linkage
    op.add_column(
        "companies",
        sa.Column("prospectpro_id", sa.String(80), nullable=True),
    )
    op.add_column(
        "companies",
        sa.Column("prospectpro_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_companies_prospectpro_id",
        "companies",
        ["org_id", "prospectpro_id"],
    )

    # AI callscripts cached per company (latest generation).
    op.add_column(
        "companies",
        sa.Column("callscript_json", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "companies",
        sa.Column("callscript_generated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Visitor events table — every pageview / form submission we know about,
    # whether from ProspectPRO or any future tracker (Leadinfo, etc).
    op.create_table(
        "visitor_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(40), nullable=False),  # 'prospectpro', 'leadinfo', ...
        sa.Column("external_id", sa.String(120), nullable=True),
        sa.Column("event_type", sa.String(40), nullable=False),  # 'pageview', 'form', ...
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("page_title", sa.Text(), nullable=True),
        sa.Column("referrer", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_visitor_events_org_company",
        "visitor_events",
        ["org_id", "company_id", "occurred_at"],
    )
    op.create_index(
        "ix_visitor_events_source_ext",
        "visitor_events",
        ["org_id", "source", "external_id"],
    )

    op.execute("ALTER TABLE visitor_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE visitor_events FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON visitor_events
        USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
        WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
        """
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON visitor_events TO salespilot_app"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON visitor_events")
    op.drop_index("ix_visitor_events_source_ext", table_name="visitor_events")
    op.drop_index("ix_visitor_events_org_company", table_name="visitor_events")
    op.drop_table("visitor_events")

    op.drop_index("ix_companies_prospectpro_id", table_name="companies")
    for col in (
        "callscript_generated_at",
        "callscript_json",
        "prospectpro_synced_at",
        "prospectpro_id",
        "country",
        "city",
        "employees",
        "pageview_count_30d",
        "last_visit_at",
        "mail_platform_checked_at",
        "mail_platform",
        "lead_score",
    ):
        op.drop_column("companies", col)
    op.execute("DROP TYPE IF EXISTS mail_platform")
