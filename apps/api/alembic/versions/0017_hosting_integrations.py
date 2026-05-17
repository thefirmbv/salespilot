"""Plesk + Openprovider integration tables.

Two integrations, six tables, all tenant-scoped with standard RLS
policy. The Plesk subscription is the billable asset (1 sub = 1 asset
= qty 1). Domains under it are reference data. Openprovider domains
are billable separately as their own asset type.

Revision ID: 0017_hosting_integrations
Revises: 0016_user_groups
Create Date: 2026-05-17
"""

from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0017_hosting_integrations"
down_revision: Union[str, None] = "0016_user_groups"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


_TENANT_TABLES = (
    "plesk_subscriptions",
    "plesk_domains",
    "plesk_state_events",
    "plesk_company_links",
    "openprovider_domains",
    "openprovider_company_links",
)


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON {table}
        USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
        WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    """)


def upgrade() -> None:
    # plesk_subscriptions
    op.create_table(
        "plesk_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plesk_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("main_domain", sa.String(255)),
        sa.Column("owner_login", sa.String(120)),
        sa.Column("owner_email", sa.String(255)),
        sa.Column("plan_name", sa.String(120)),
        sa.Column("plan_id", sa.Integer),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("disk_used_mb", sa.Integer, nullable=False, server_default="0"),
        sa.Column("disk_limit_mb", sa.Integer),
        sa.Column("traffic_used_mb", sa.Integer, nullable=False, server_default="0"),
        sa.Column("mailboxes_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("databases_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_in_plesk", sa.DateTime(timezone=True)),
        sa.Column("halopsa_asset_id", sa.Integer),
        sa.Column("halopsa_synced_at", sa.DateTime(timezone=True)),
        sa.Column("last_polled", sa.DateTime(timezone=True)),
        sa.Column("last_status_change", sa.DateTime(timezone=True)),
        sa.Column("raw", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "plesk_id", name="uq_plesk_subs_org_pid"),
    )
    op.create_index("ix_plesk_subs_plesk_id", "plesk_subscriptions", ["plesk_id"])
    op.create_index("ix_plesk_subs_main_domain", "plesk_subscriptions", ["main_domain"])
    op.create_index("ix_plesk_subs_org_status", "plesk_subscriptions", ["org_id", "status"])
    op.create_index("ix_plesk_subs_halopsa_asset_id", "plesk_subscriptions", ["halopsa_asset_id"])

    # plesk_domains
    op.create_table(
        "plesk_domains",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plesk_id", sa.String(64), nullable=False),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("plesk_subscriptions.id", ondelete="CASCADE")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(32)),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("ssl_enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("last_polled", sa.DateTime(timezone=True)),
        sa.Column("raw", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "plesk_id", name="uq_plesk_domains_org_pid"),
    )
    op.create_index("ix_plesk_domains_plesk_id", "plesk_domains", ["plesk_id"])
    op.create_index("ix_plesk_domains_name", "plesk_domains", ["name"])

    # plesk_state_events
    op.create_table(
        "plesk_state_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("plesk_subscriptions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("previous_status", sa.String(32)),
        sa.Column("new_status", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_plesk_state_events_occurred", "plesk_state_events", ["org_id", "occurred_at"])
    op.create_index("ix_plesk_state_events_sub", "plesk_state_events", ["subscription_id"])

    # plesk_company_links
    op.create_table(
        "plesk_company_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("plesk_subscriptions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("halopsa_product_id", sa.Integer),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "subscription_id", name="uq_plesk_links_subscription"),
    )

    # openprovider_domains
    op.create_table(
        "openprovider_domains",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("op_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("extension", sa.String(16)),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("auto_renew", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("registered_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("nameservers", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("owner_handle", sa.String(120)),
        sa.Column("is_locked", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("halopsa_asset_id", sa.Integer),
        sa.Column("halopsa_synced_at", sa.DateTime(timezone=True)),
        sa.Column("last_polled", sa.DateTime(timezone=True)),
        sa.Column("raw", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "op_id", name="uq_op_domains_org_opid"),
    )
    op.create_index("ix_op_domains_op_id", "openprovider_domains", ["op_id"])
    op.create_index("ix_op_domains_name", "openprovider_domains", ["name"])
    op.create_index("ix_op_domains_org_status", "openprovider_domains", ["org_id", "status"])
    op.create_index("ix_op_domains_expires", "openprovider_domains", ["org_id", "expires_at"])
    op.create_index("ix_op_domains_halopsa_asset_id", "openprovider_domains", ["halopsa_asset_id"])

    # openprovider_company_links
    op.create_table(
        "openprovider_company_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("openprovider_domains.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("halopsa_product_id", sa.Integer),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "domain_id", name="uq_op_links_domain"),
    )

    for t in _TENANT_TABLES:
        _enable_rls(t)


def downgrade() -> None:
    for t in reversed(_TENANT_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {t}")
        op.drop_table(t)
