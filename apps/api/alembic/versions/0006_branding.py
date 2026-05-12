"""Org branding (logo + accent colour) and deal enrichment fields.

Revision ID: 0006_branding
Revises: 0005_quotations
Create Date: 2026-05-12
"""

from typing import Union
import sqlalchemy as sa

from alembic import op

revision: str = "0006_branding"
down_revision: Union[str, None] = "0005_quotations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Logo + brand colour per organisation.
    op.add_column("organizations", sa.Column("logo_url", sa.String(500), nullable=True))
    op.add_column("organizations", sa.Column("brand_color", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "brand_color")
    op.drop_column("organizations", "logo_url")
