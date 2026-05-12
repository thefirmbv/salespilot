"""Add company source/halopsa_id and integrations table.

Revision ID: 0002_halopsa
Revises: 0001_initial
Create Date: 2026-05-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_halopsa"
down_revision: Union[str, None] = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enum for company source
    op.execute(
        "CREATE TYPE company_source AS ENUM "
        "('salespilot', 'halopsa', 'halopsa_pushed')"
    )

    # Add columns to companies
    op.add_column(
        "companies",
        sa.Column(
            "source",
            postgresql.ENUM(
                "salespilot", "halopsa", "halopsa_pushed",
                name="company_source", create_type=False,
            ),
            nullable=False,
            server_default="salespilot",
        ),
    )
    op.add_column(
        "companies",
        sa.Column("halopsa_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "companies",
        sa.Column("halopsa_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_companies_halopsa_id", "companies", ["org_id", "halopsa_id"], unique=False
    )

    # Integrations table: per-org credentials for external systems.
    op.create_table(
        "integrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        # kind is 'halopsa', 'gmail', 'azure', etc. Per-(org, kind) uniqueness.
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        # config_json: free-form JSONB. For HaloPSA contains:
        #   { "base_url": "...", "client_id": "...", "client_secret": "...",
        #     "tenant": "optional", "scopes": ["all"] }
        # NOTE: secrets are stored as-is for v1. Encryption-at-rest in the app
        # layer is a TODO; the operational mitigation right now is that this
        # table is only accessible through the API which runs RLS, and the
        # database itself is on a private network.
        sa.Column("config_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(20), nullable=True),
        sa.Column("last_sync_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("org_id", "kind", name="uq_integrations_org_kind"),
    )
    op.create_index("ix_integrations_org_id", "integrations", ["org_id"])

    # RLS on integrations.
    op.execute("ALTER TABLE integrations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE integrations FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON integrations
        USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
        WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
        """
    )

    # Grant the application role the necessary privileges on the new table.
    # The migration runs as the DB owner, which by default is the only one
    # with rights — without these grants, the runtime app sees zero rows.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON integrations TO salespilot_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON integrations")
    op.execute("ALTER TABLE integrations DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_integrations_org_id", table_name="integrations")
    op.drop_table("integrations")

    op.drop_index("ix_companies_halopsa_id", table_name="companies")
    op.drop_column("companies", "halopsa_synced_at")
    op.drop_column("companies", "halopsa_id")
    op.drop_column("companies", "source")
    op.execute("DROP TYPE IF EXISTS company_source")
