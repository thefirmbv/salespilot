"""Synced absences tabel voor NMBRS -> HaloPSA verlof-sync.

Houdt bij welke NMBRS-absence-records we al naar HaloPSA Appointment
hebben gepusht, met halopsa_appointment_id voor latere update/delete.

Revision: 0023_synced_absences
Revises: 0022_employee_halopsa_link
"""

from typing import Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0023_synced_absences"
down_revision: Union[str, None] = "0022_employee_halopsa_link"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "synced_absences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("nmbrs_absence_id", sa.Integer, nullable=False),
        sa.Column("nmbrs_company_id", sa.String(40)),
        sa.Column("halopsa_appointment_id", sa.Integer),
        # 'vacation' | 'sick' | 'special_leave' | 'other'
        sa.Column("absence_type_code", sa.String(20)),
        sa.Column("absence_type_label", sa.String(120)),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date),
        sa.Column("percentage", sa.Integer),  # ziekmelding-percentage
        sa.Column("comment", sa.Text),
        sa.Column("subject", sa.String(255)),
        sa.Column("last_modified_at", sa.DateTime(timezone=True)),
        sa.Column("synced_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "nmbrs_absence_id",
                            name="uq_synced_absences_org_nmbrs"),
    )
    op.create_index("ix_synced_absences_employee",
                    "synced_absences", ["employee_id"])

    op.execute("ALTER TABLE synced_absences ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE synced_absences FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON synced_absences
        USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
        WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON synced_absences")
    op.execute("ALTER TABLE synced_absences DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_synced_absences_employee", table_name="synced_absences")
    op.drop_table("synced_absences")
