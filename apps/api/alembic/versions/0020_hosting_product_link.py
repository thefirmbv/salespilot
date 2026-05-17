"""Per-asset product link (voor variabele tarieven).

Verplaatst halopsa_product_id van link-table naar de subscription/
domain row zelf. Reden: 1 klant kan meerdere subs/domeinen hebben met
verschillende tarieven. Voorbeeld:
   Klant X heeft "Hosting Basis" (€20/mnd) + "Hosting Pro" (€50/mnd)

Voegt ook halopsa_assettype_id toe per row: de HaloPSA AssetType waar
het asset onder valt. Beide AssetTypes vallen onder group 124
("Domeinnaam en Hosting").

Revision: 0020_hosting_product_link
Revises: 0019_openprovider_audit
"""

from typing import Union
from alembic import op
import sqlalchemy as sa


revision: str = "0020_hosting_product_link"
down_revision: Union[str, None] = "0019_openprovider_audit"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # Plesk: per subscription een eigen product (= tarief)
    op.add_column("plesk_subscriptions",
        sa.Column("halopsa_product_id", sa.Integer))
    op.add_column("plesk_subscriptions",
        sa.Column("halopsa_assettype_id", sa.Integer))
    op.create_index("ix_plesk_subs_product", "plesk_subscriptions", ["halopsa_product_id"])

    # Openprovider: idem per domein
    op.add_column("openprovider_domains",
        sa.Column("halopsa_product_id", sa.Integer))
    op.add_column("openprovider_domains",
        sa.Column("halopsa_assettype_id", sa.Integer))
    op.create_index("ix_op_domains_product", "openprovider_domains", ["halopsa_product_id"])


def downgrade() -> None:
    op.drop_index("ix_op_domains_product", table_name="openprovider_domains")
    op.drop_column("openprovider_domains", "halopsa_assettype_id")
    op.drop_column("openprovider_domains", "halopsa_product_id")
    op.drop_index("ix_plesk_subs_product", table_name="plesk_subscriptions")
    op.drop_column("plesk_subscriptions", "halopsa_assettype_id")
    op.drop_column("plesk_subscriptions", "halopsa_product_id")
