"""Employees + asset inventory (auto/telefoon/laptop/overig).

Twee tabellen:
  employees           -- medewerker (naam, email, status, NMBRS-id later)
  employee_assets     -- per medewerker een lijst items van diverse types

Asset-types met type-specifieke velden in `details` JSONB:
  vehicle  -- license_plate, brand, model, fuel, year
  phone    -- imei, model, brand, phone_number
  laptop   -- serial, model, brand, processor, ram_gb
  other    -- alleen vrije description + serial/identifier

Beide tabellen tenant-scoped via RLS.

Revision: 0021_employees_inventory
Revises: 0020_hosting_product_link
"""

from typing import Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0021_employees_inventory"
down_revision: Union[str, None] = "0020_hosting_product_link"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


_TENANT_TABLES = ("employees", "employee_assets")


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON {table}
        USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
        WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    """)


def upgrade() -> None:
    # employees
    op.create_table(
        "employees",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("full_name", sa.String(160), nullable=False),
        sa.Column("email", sa.String(255)),
        sa.Column("phone", sa.String(40)),
        sa.Column("role", sa.String(120)),  # functie
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="active"),  # active/inactive/leave
        sa.Column("nmbrs_employee_id", sa.String(40)),  # voor latere sync
        sa.Column("nmbrs_company_id", sa.String(40)),
        sa.Column("started_at", sa.Date),
        sa.Column("ended_at", sa.Date),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "email", name="uq_employees_org_email"),
    )
    op.create_index("ix_employees_org_status", "employees", ["org_id", "status"])
    op.create_index("ix_employees_nmbrs", "employees", ["nmbrs_employee_id"])

    # employee_assets
    op.create_table(
        "employee_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("asset_type", sa.String(20), nullable=False),
        # 'vehicle'|'phone'|'laptop'|'other'
        sa.Column("label", sa.String(160), nullable=False),
        # Korte beschrijving voor lijst-weergave ('MacBook Pro 16'')
        sa.Column("identifier", sa.String(120)),
        # Algemeen identifier-veld (kenteken / IMEI / serial)
        sa.Column("details", postgresql.JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        # Type-specifieke velden, vrij vorm
        sa.Column("assigned_at", sa.Date),
        sa.Column("returned_at", sa.Date),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_employee_assets_employee",
                    "employee_assets", ["employee_id"])
    op.create_index("ix_employee_assets_org_type",
                    "employee_assets", ["org_id", "asset_type"])

    for t in _TENANT_TABLES:
        _enable_rls(t)


def downgrade() -> None:
    for t in _TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {t}")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_employee_assets_org_type",
                  table_name="employee_assets")
    op.drop_index("ix_employee_assets_employee",
                  table_name="employee_assets")
    op.drop_table("employee_assets")
    op.drop_index("ix_employees_nmbrs", table_name="employees")
    op.drop_index("ix_employees_org_status", table_name="employees")
    op.drop_table("employees")
