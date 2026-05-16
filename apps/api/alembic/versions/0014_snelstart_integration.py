"""Add SnelStart 12 integration row -- handled at app startup.

The integrations table has tenant_isolation RLS keyed on the
app.current_org_id GUC. Alembic runs as the salespilot_app role which
does NOT bypass RLS, so we can't easily seed cross-tenant rows from a
migration step. Instead we let the app-startup seeder
(salespilot.startup.ensure_default_integrations) create the row on
first boot per org -- it has access to a tenant_session() and runs as
needed.

This migration is intentionally a no-op so future alembic upgrades
don't fail on the seed step. The row appears the next time the API
container starts.

Revision ID: 0014_snelstart_integration
Revises: 0013_personal_calendar
Create Date: 2026-05-15
"""

from typing import Union


revision: str = "0014_snelstart_integration"
down_revision: Union[str, None] = "0013_personal_calendar"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
