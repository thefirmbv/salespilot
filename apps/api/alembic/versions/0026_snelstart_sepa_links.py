"""Snelstart SEPA links: track Snelstart verkoopboekingen die we hebben
gepatched met een doorlopende incassomachtiging.

Achtergrond
-----------
HaloPSA pusht verkoopboekingen naar Snelstart maar zonder de
`doorlopendeIncassoMachtiging` referentie ingevuld -- daardoor komen
SEPA-klant-facturen niet in het incassobestand. SalesPilot vult dit
veld achteraf in via de Snelstart B2B API.

Deze tabel houdt bij welke boekingen we al hebben gepatched zodat
de sync idempotent is en we niet steeds dezelfde rij oplopen.

Plus: per Snelstart-relatie houden we bij welke IncassoMachtiging
(GUID + UMR) we hebben aangemaakt, zodat we hem niet dubbel maken.

Revision: 0026_snelstart_sepa_links
Revises: 0025_leave_sync_and_delete
"""

from typing import Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0026_snelstart_sepa_links"
down_revision: Union[str, None] = "0025_leave_sync_and_delete"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # Track welke verkoopboekingen al gepatched zijn met machtiging-ref
    op.create_table(
        "snelstart_sepa_patches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False),
        # Snelstart verkoopboeking GUID
        sa.Column("snelstart_factuur_id", sa.String(40), nullable=False),
        sa.Column("snelstart_factuurnummer", sa.String(40)),
        # De relatie en machtiging die we hebben gekoppeld
        sa.Column("snelstart_relatie_id", sa.String(40)),
        sa.Column("snelstart_relatie_naam", sa.String(200)),
        sa.Column("snelstart_machtiging_id", sa.String(40)),
        # UMR uit signed_mandates (= ons interne SEPA kenmerk)
        sa.Column("umr", sa.String(35)),
        # Outcome
        # 'patched' = succesvol gepatched
        # 'skipped_already_set' = factuur had al een machtiging-ref
        # 'skipped_no_mandate' = klant heeft geen signed_mandate
        # 'skipped_no_match' = klant kon niet gematched worden in Snelstart
        # 'error' = patch faalde
        sa.Column("outcome", sa.String(40), nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("patched_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "snelstart_factuur_id",
                            name="uq_snelstart_sepa_patches_factuur"),
    )
    op.create_index("ix_snelstart_sepa_patches_outcome",
                    "snelstart_sepa_patches", ["org_id", "outcome"])

    op.execute("ALTER TABLE snelstart_sepa_patches ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE snelstart_sepa_patches FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON snelstart_sepa_patches
        USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
        WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    """)

    # Per Snelstart-relatie: welke machtiging is gekoppeld?
    # We onthouden de mapping signed_mandate <-> snelstart machtiging guid
    # zodat bij volgende sync we direct kunnen koppelen.
    op.create_table(
        "snelstart_machtiging_map",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("signed_mandate_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("signed_mandates.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("snelstart_relatie_id", sa.String(40), nullable=False),
        sa.Column("snelstart_machtiging_id", sa.String(40), nullable=False),
        sa.Column("umr", sa.String(35), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "snelstart_machtiging_id",
                            name="uq_snelstart_machtiging_id"),
        sa.UniqueConstraint("org_id", "signed_mandate_id",
                            name="uq_snelstart_machtiging_per_mandate"),
    )

    op.execute("ALTER TABLE snelstart_machtiging_map ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE snelstart_machtiging_map FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON snelstart_machtiging_map
        USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
        WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON snelstart_machtiging_map")
    op.execute("ALTER TABLE snelstart_machtiging_map DISABLE ROW LEVEL SECURITY")
    op.drop_table("snelstart_machtiging_map")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON snelstart_sepa_patches")
    op.execute("ALTER TABLE snelstart_sepa_patches DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_snelstart_sepa_patches_outcome",
                  table_name="snelstart_sepa_patches")
    op.drop_table("snelstart_sepa_patches")
