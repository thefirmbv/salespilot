"""Audit log for write actions on hosting integrations.

Captures who registered/cancelled domains, with the API response so we
can debug failures and have a paper trail for billing.

Revision ID: 0019_openprovider_audit
Revises: 0018_plesk_servers
"""

from typing import Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0019_openprovider_audit"
down_revision: Union[str, None] = "0018_plesk_servers"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "openprovider_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("domain_name", sa.String(255)),
        sa.Column("domain_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("openprovider_domains.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(16), nullable=False, server_default="ok"),
        sa.Column("request_payload", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("response_payload", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_message", sa.Text),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_op_audit_occurred", "openprovider_audit_log", ["org_id", "occurred_at"])
    op.create_index("ix_op_audit_domain", "openprovider_audit_log", ["domain_id"])
    op.create_index("ix_op_audit_action", "openprovider_audit_log", ["action"])

    op.execute("ALTER TABLE openprovider_audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE openprovider_audit_log FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON openprovider_audit_log
        USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
        WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON openprovider_audit_log")
    op.drop_table("openprovider_audit_log")
