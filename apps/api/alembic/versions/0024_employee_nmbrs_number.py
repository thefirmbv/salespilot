"""Voeg nmbrs_employee_number toe voor SOAP <-> REST matching.

NMBRS REST gebruikt UUID-employeeId's, SOAP gebruikt integer-Id's.
Beide kanten hebben echter de same employeeNumber (1, 2, 5, 8...).
We slaan dat nummer als matching-key op.

Revision: 0024_employee_nmbrs_number
Revises: 0023_synced_absences
"""

from typing import Union
from alembic import op
import sqlalchemy as sa


revision: str = "0024_employee_nmbrs_number"
down_revision: Union[str, None] = "0023_synced_absences"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column("employees",
        sa.Column("nmbrs_employee_number", sa.Integer, nullable=True))
    op.create_index("ix_employees_nmbrs_number",
                    "employees", ["nmbrs_employee_number"])


def downgrade() -> None:
    op.drop_index("ix_employees_nmbrs_number", table_name="employees")
    op.drop_column("employees", "nmbrs_employee_number")
