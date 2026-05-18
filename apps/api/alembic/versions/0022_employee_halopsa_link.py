"""Employee <-> HaloPSA agent koppeling.

Voor verlof-sync moeten we weten welke HaloPSA-agent bij welke
NMBRS-medewerker hoort. Naam/email-match is onbetrouwbaar omdat
medewerkers vaak hun prive-email in NMBRS hebben.

Voegt halopsa_agent_id (int) toe + index.

Revision: 0022_employee_halopsa_link
Revises: 0021_employees_inventory
"""

from typing import Union
from alembic import op
import sqlalchemy as sa


revision: str = "0022_employee_halopsa_link"
down_revision: Union[str, None] = "0021_employees_inventory"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column("employees",
        sa.Column("halopsa_agent_id", sa.Integer, nullable=True))
    op.add_column("employees",
        sa.Column("halopsa_agent_name", sa.String(160), nullable=True))
    op.create_index("ix_employees_halopsa_agent",
                    "employees", ["halopsa_agent_id"])


def downgrade() -> None:
    op.drop_index("ix_employees_halopsa_agent", table_name="employees")
    op.drop_column("employees", "halopsa_agent_name")
    op.drop_column("employees", "halopsa_agent_id")
