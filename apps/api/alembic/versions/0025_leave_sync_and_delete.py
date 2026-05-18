"""Leave-sync + DELETE-flow voor absences.

NMBRS Leave_GetList retourneert GEEN unieke ID per leave-record,
alleen Start/End/Hours/Description. We bouwen daarom een
deterministische business-key: hash van (employee_number, start,
end, hours, description). Voor ziekte gebruiken we de echte
AbsenceId (uniek).

Plus soft-delete kolommen voor DELETE-flow naar HaloPSA.

Revision: 0025_leave_sync_and_delete
Revises: 0024_employee_nmbrs_number
"""

from typing import Union
from alembic import op
import sqlalchemy as sa


revision: str = "0025_leave_sync_and_delete"
down_revision: Union[str, None] = "0024_employee_nmbrs_number"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # nmbrs_absence_id kan nu NULL zijn (Leave-records hebben geen Id)
    op.alter_column("synced_absences", "nmbrs_absence_id",
                    existing_type=sa.Integer, nullable=True)
    # Business-key voor records zonder NMBRS-id (Leave)
    op.add_column("synced_absences",
        sa.Column("business_key", sa.String(120), nullable=True))
    # Soft-delete tracking
    op.add_column("synced_absences",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    # Source-type: 'absence' (NMBRS ziekte) of 'leave' (NMBRS vakantie)
    op.add_column("synced_absences",
        sa.Column("source", sa.String(20), nullable=False,
                  server_default="absence"))

    # Drop oude unique constraint, vervang met source-aware unique
    op.drop_constraint("uq_synced_absences_org_nmbrs", "synced_absences",
                       type_="unique")
    op.create_unique_constraint(
        "uq_synced_absences_org_business",
        "synced_absences", ["org_id", "source", "business_key"],
    )
    op.create_index("ix_synced_absences_source_active",
                    "synced_absences", ["org_id", "source", "deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_synced_absences_source_active",
                  table_name="synced_absences")
    op.drop_constraint("uq_synced_absences_org_business",
                       "synced_absences", type_="unique")
    op.create_unique_constraint(
        "uq_synced_absences_org_nmbrs",
        "synced_absences", ["org_id", "nmbrs_absence_id"],
    )
    op.drop_column("synced_absences", "source")
    op.drop_column("synced_absences", "deleted_at")
    op.drop_column("synced_absences", "business_key")
    op.alter_column("synced_absences", "nmbrs_absence_id",
                    existing_type=sa.Integer, nullable=False)
