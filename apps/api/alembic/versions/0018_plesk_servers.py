"""Plesk multi-server support.

Replaces the single 'plesk' integration row with a model where you can
add multiple servers. Each subscription is linked to one server. The
integration row stays for poll-interval + asset_type defaults; servers
table holds per-server credentials.

Revision ID: 0018_plesk_servers
Revises: 0017_hosting_integrations
"""

from typing import Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0018_plesk_servers"
down_revision: Union[str, None] = "0017_hosting_integrations"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "plesk_servers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("base_url", sa.String(255), nullable=False),
        sa.Column("api_key", sa.Text, nullable=False, server_default=""),
        sa.Column("verify_tls", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("last_sync_at", sa.DateTime(timezone=True)),
        sa.Column("last_sync_status", sa.String(32)),
        sa.Column("last_sync_message", sa.Text),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "name", name="uq_plesk_servers_org_name"),
    )

    op.add_column("plesk_subscriptions",
        sa.Column("server_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("plesk_servers.id", ondelete="SET NULL")),
    )
    op.create_index("ix_plesk_subs_server_id", "plesk_subscriptions", ["server_id"])
    op.add_column("plesk_domains",
        sa.Column("server_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("plesk_servers.id", ondelete="SET NULL")),
    )

    op.execute("ALTER TABLE plesk_servers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE plesk_servers FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON plesk_servers
        USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
        WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    """)


def downgrade() -> None:
    op.drop_index("ix_plesk_subs_server_id", table_name="plesk_subscriptions")
    op.drop_column("plesk_domains", "server_id")
    op.drop_column("plesk_subscriptions", "server_id")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON plesk_servers")
    op.drop_table("plesk_servers")
