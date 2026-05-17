"""UniFi monitoring tables.

Five tables backing the UniFi mini-portal:
  - unifi_hosts          consoles (Dream Machines)
  - unifi_sites          network sites under a host
  - unifi_devices        AP's, switches, cameras, gateways
  - unifi_state_events   online/offline transitions for incidents feed
  - unifi_company_links  host -> SalesPilot company for billing

All tenant-scoped with the standard RLS policy keyed on
app.current_org_id GUC.

Revision ID: 0015_unifi_monitoring
Revises: 0014_snelstart_integration
Create Date: 2026-05-16
"""

from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0015_unifi_monitoring"
down_revision: Union[str, None] = "0014_snelstart_integration"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


_TENANT_TABLES = (
    "unifi_hosts", "unifi_sites", "unifi_devices",
    "unifi_state_events", "unifi_company_links",
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
    # ------------------------------------------------------------------
    # unifi_hosts
    # ------------------------------------------------------------------
    op.create_table(
        "unifi_hosts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ubnt_host_id", sa.String(255), nullable=False),
        sa.Column("hardware_id", sa.String(64)),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("owner_email", sa.String(255)),
        sa.Column("model", sa.String(64)),
        sa.Column("model_short", sa.String(32)),
        sa.Column("firmware_version", sa.String(64)),
        sa.Column("is_blocked", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("is_online", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("last_connection_change", sa.DateTime(timezone=True)),
        sa.Column("registration_time", sa.DateTime(timezone=True)),
        sa.Column("last_polled", sa.DateTime(timezone=True)),
        sa.Column("raw", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "ubnt_host_id", name="uq_unifi_hosts_org_ubnt"),
    )
    op.create_index("ix_unifi_hosts_ubnt_host_id", "unifi_hosts", ["ubnt_host_id"])
    op.create_index("ix_unifi_hosts_online", "unifi_hosts", ["org_id", "is_online"])

    # ------------------------------------------------------------------
    # unifi_sites
    # ------------------------------------------------------------------
    op.create_table(
        "unifi_sites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ubnt_site_id", sa.String(64), nullable=False),
        sa.Column("host_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unifi_hosts.id", ondelete="CASCADE")),
        sa.Column("name", sa.String(120), nullable=False, server_default="default"),
        sa.Column("description", sa.String(255)),
        sa.Column("gateway_mac", sa.String(32)),
        sa.Column("timezone", sa.String(64)),
        sa.Column("total_devices", sa.Integer, nullable=False, server_default="0"),
        sa.Column("offline_devices", sa.Integer, nullable=False, server_default="0"),
        sa.Column("wifi_clients", sa.Integer, nullable=False, server_default="0"),
        sa.Column("wired_clients", sa.Integer, nullable=False, server_default="0"),
        sa.Column("guest_clients", sa.Integer, nullable=False, server_default="0"),
        sa.Column("critical_notifications", sa.Integer, nullable=False, server_default="0"),
        sa.Column("raw", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "ubnt_site_id", name="uq_unifi_sites_org_ubnt"),
    )
    op.create_index("ix_unifi_sites_ubnt_site_id", "unifi_sites", ["ubnt_site_id"])

    # ------------------------------------------------------------------
    # unifi_devices
    # ------------------------------------------------------------------
    op.create_table(
        "unifi_devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ubnt_device_id", sa.String(64), nullable=False),
        sa.Column("host_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unifi_hosts.id", ondelete="CASCADE")),
        sa.Column("mac", sa.String(32)),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("model", sa.String(64)),
        sa.Column("model_short", sa.String(32)),
        sa.Column("product_line", sa.String(32)),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("firmware_version", sa.String(64)),
        sa.Column("firmware_status", sa.String(32)),
        sa.Column("update_available", sa.String(64)),
        sa.Column("is_console", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("is_managed", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("status", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("startup_time", sa.DateTime(timezone=True)),
        sa.Column("note", sa.Text),
        sa.Column("halopsa_asset_id", sa.Integer),
        sa.Column("halopsa_synced_at", sa.DateTime(timezone=True)),
        sa.Column("last_polled", sa.DateTime(timezone=True)),
        sa.Column("last_status_change", sa.DateTime(timezone=True)),
        sa.Column("raw", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "ubnt_device_id", name="uq_unifi_devices_org_ubnt"),
    )
    op.create_index("ix_unifi_devices_ubnt_device_id", "unifi_devices", ["ubnt_device_id"])
    op.create_index("ix_unifi_devices_mac", "unifi_devices", ["mac"])
    op.create_index("ix_unifi_devices_halopsa_asset_id", "unifi_devices", ["halopsa_asset_id"])
    op.create_index("ix_unifi_devices_host_status", "unifi_devices", ["host_id", "status"])
    op.create_index("ix_unifi_devices_org_status", "unifi_devices", ["org_id", "status"])

    # ------------------------------------------------------------------
    # unifi_state_events
    # ------------------------------------------------------------------
    op.create_table(
        "unifi_state_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_kind", sa.String(16), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("previous_status", sa.String(32)),
        sa.Column("new_status", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Integer),
        sa.Column("snapshot", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_unifi_state_events_occurred", "unifi_state_events", ["org_id", "occurred_at"])
    op.create_index("ix_unifi_state_events_entity", "unifi_state_events", ["entity_kind", "entity_id"])

    # ------------------------------------------------------------------
    # unifi_company_links
    # ------------------------------------------------------------------
    op.create_table(
        "unifi_company_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("host_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unifi_hosts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("halopsa_product_id", sa.Integer),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "host_id", name="uq_unifi_company_links_host"),
    )

    # RLS on all five
    for t in _TENANT_TABLES:
        _enable_rls(t)


def downgrade() -> None:
    for t in reversed(_TENANT_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {t}")
        op.drop_table(t)
