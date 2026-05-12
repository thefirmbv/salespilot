"""Quotations sourced from HaloPSA + auto follow-up activities.

Revision ID: 0005_quotations
Revises: 0004_autopilot
Create Date: 2026-05-12
"""

from typing import Union
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_quotations"
down_revision: Union[str, None] = "0004_autopilot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quotations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("deal_id", postgresql.UUID(as_uuid=True), nullable=True),
        # HaloPSA fields
        sa.Column("halopsa_id", sa.Integer(), nullable=False),
        sa.Column("reference", sa.String(80), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        # Status: 'draft' | 'sent' | 'accepted' | 'rejected' | 'expired'
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("status_id_halopsa", sa.Integer(), nullable=True),
        sa.Column("status_label_halopsa", sa.String(80), nullable=True),
        # Amounts
        sa.Column("amount_net", sa.Numeric(14, 2), nullable=True),
        sa.Column("amount_gross", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        # Dates
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        # Raw HaloPSA payload for debugging.
        sa.Column("raw", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("org_id", "halopsa_id", name="uq_quotations_halopsa_id"),
    )
    op.create_index("ix_quotations_org_status", "quotations", ["org_id", "status"])
    op.create_index("ix_quotations_company", "quotations", ["org_id", "company_id"])
    op.create_index("ix_quotations_deal", "quotations", ["org_id", "deal_id"])
    op.create_index("ix_quotations_valid_until", "quotations", ["org_id", "valid_until"])

    op.execute("ALTER TABLE quotations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE quotations FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON quotations
        USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
        WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON quotations TO salespilot_app")

    # Link activities back to quotations so reminders know what they belong to.
    op.add_column(
        "activities",
        sa.Column("quotation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_activities_quotation",
        "activities",
        "quotations",
        ["quotation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Lets us answer "is there already a reminder for stage X (14 or 28) of this quote?"
    op.add_column(
        "activities",
        sa.Column("reminder_kind", sa.String(40), nullable=True),
    )
    op.create_index(
        "ix_activities_quotation_reminder",
        "activities",
        ["org_id", "quotation_id", "reminder_kind"],
    )


def downgrade() -> None:
    op.drop_index("ix_activities_quotation_reminder", table_name="activities")
    op.drop_column("activities", "reminder_kind")
    op.drop_constraint("fk_activities_quotation", "activities", type_="foreignkey")
    op.drop_column("activities", "quotation_id")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON quotations")
    op.drop_index("ix_quotations_valid_until", table_name="quotations")
    op.drop_index("ix_quotations_deal", table_name="quotations")
    op.drop_index("ix_quotations_company", table_name="quotations")
    op.drop_index("ix_quotations_org_status", table_name="quotations")
    op.drop_table("quotations")
