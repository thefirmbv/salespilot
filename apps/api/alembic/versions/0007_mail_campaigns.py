"""HaloPSA Mail Campaigns import.

Revision ID: 0007_mail_campaigns
Revises: 0006_branding
Create Date: 2026-05-12
"""

from typing import Union
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_mail_campaigns"
down_revision: Union[str, None] = "0006_branding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One row per HaloPSA mail campaign.
    op.create_table(
        "mail_campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("halopsa_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("from_name", sa.String(120), nullable=True),
        sa.Column("from_email", sa.String(200), nullable=True),
        # 'draft' | 'scheduled' | 'sending' | 'sent' | 'paused' | 'cancelled'
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("status_label_halopsa", sa.String(80), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        # Aggregate counters (denormalised for dashboard speed).
        sa.Column("recipients_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delivered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("opened_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clicked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bounced_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unsubscribed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("complained_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("org_id", "halopsa_id", name="uq_mail_campaigns_halopsa_id"),
    )
    op.create_index("ix_mail_campaigns_status", "mail_campaigns", ["org_id", "status"])
    op.create_index("ix_mail_campaigns_sent_at", "mail_campaigns", ["org_id", "sent_at"])

    op.execute("ALTER TABLE mail_campaigns ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE mail_campaigns FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON mail_campaigns
        USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
        WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON mail_campaigns TO salespilot_app")

    # One row per recipient per campaign.
    op.create_table(
        "mail_campaign_recipients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(200), nullable=True),
        # 'queued' | 'sent' | 'delivered' | 'opened' | 'clicked' | 'bounced'
        # | 'complained' | 'unsubscribed' | 'failed'
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clicked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bounced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unsubscribed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("open_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("click_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("halopsa_recipient_id", sa.Integer(), nullable=True),
        sa.Column("raw", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["mail_campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_mcr_campaign_status",
        "mail_campaign_recipients",
        ["org_id", "campaign_id", "status"],
    )
    op.create_index(
        "ix_mcr_company",
        "mail_campaign_recipients",
        ["org_id", "company_id"],
        postgresql_where=sa.text("company_id IS NOT NULL"),
    )
    op.create_index(
        "ix_mcr_email",
        "mail_campaign_recipients",
        ["org_id", "email"],
    )

    op.execute("ALTER TABLE mail_campaign_recipients ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE mail_campaign_recipients FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON mail_campaign_recipients
        USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
        WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON mail_campaign_recipients TO salespilot_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON mail_campaign_recipients")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON mail_campaigns")
    op.drop_index("ix_mcr_email", table_name="mail_campaign_recipients")
    op.drop_index("ix_mcr_company", table_name="mail_campaign_recipients")
    op.drop_index("ix_mcr_campaign_status", table_name="mail_campaign_recipients")
    op.drop_table("mail_campaign_recipients")
    op.drop_index("ix_mail_campaigns_sent_at", table_name="mail_campaigns")
    op.drop_index("ix_mail_campaigns_status", table_name="mail_campaigns")
    op.drop_table("mail_campaigns")
