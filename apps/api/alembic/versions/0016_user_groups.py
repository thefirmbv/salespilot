"""Add 'groups' array to org_memberships for rechten-systeem.

We use a TEXT[] column on the existing membership row rather than a
separate roles-table because:
  - Five fixed group names (administrators, marketing, sales,
    financieel, agendagebruikers) -- no need for a CRUD-table
  - Multi-group membership is just a list, queryable with @> operator
  - One less JOIN on every protected endpoint
  - Easy to seed everyone as administrators initially

Seed rule (per user request): every existing user becomes
'administrators' so they keep current access. The page-policies layer
in the API will still consult the array, but for admins it returns
allow-all. Later we strip groups per user via /settings/access.

Revision ID: 0016_user_groups
Revises: 0015_unifi_monitoring
Create Date: 2026-05-17
"""

from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0016_user_groups"
down_revision: Union[str, None] = "0015_unifi_monitoring"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


# The canonical set. Anything in groups[] outside this set is ignored.
KNOWN_GROUPS = (
    "administrators",
    "marketing",
    "sales",
    "financieel",
    "agendagebruikers",
)


def upgrade() -> None:
    # 1) Add the column (empty array default)
    op.add_column(
        "org_memberships",
        sa.Column(
            "groups",
            postgresql.ARRAY(sa.Text),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
    )
    # 2) Index for fast `groups @> ARRAY['administrators']` queries
    op.create_index(
        "ix_org_memberships_groups",
        "org_memberships",
        ["groups"],
        postgresql_using="gin",
    )
    # 3) Seed: everyone in IT-Gemak org becomes 'administrators' so they
    #    keep full access; UI lets admins strip down later.
    op.execute("""
        UPDATE org_memberships
           SET groups = ARRAY['administrators']::text[]
         WHERE cardinality(groups) = 0
    """)


def downgrade() -> None:
    op.drop_index("ix_org_memberships_groups", table_name="org_memberships")
    op.drop_column("org_memberships", "groups")
