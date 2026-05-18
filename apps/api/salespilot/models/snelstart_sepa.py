"""Models voor Snelstart SEPA-link tracking.

Doel: zorgen dat de SalesPilot tussenlaag idempotent is. Bij elke
sync onthouden we welke Verkoopboekingen we al hebben gepatched en
welke IncassoMachtigingen we hebben aangemaakt op welke Snelstart-relatie.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from salespilot.models import Base


class SnelstartSepaPatch(Base):
    """Audit-log van Verkoopboeking-patches naar Snelstart.

    Eén rij per verkoopboeking; tweede sync-run die dezelfde boeking
    tegenkomt schrijft niets meer (UniqueConstraint).
    """

    __tablename__ = "snelstart_sepa_patches"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "snelstart_factuur_id",
            name="uq_snelstart_sepa_patches_factuur",
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    snelstart_factuur_id: Mapped[str] = mapped_column(String(40), nullable=False)
    snelstart_factuurnummer: Mapped[str | None] = mapped_column(String(40))
    snelstart_relatie_id: Mapped[str | None] = mapped_column(String(40))
    snelstart_relatie_naam: Mapped[str | None] = mapped_column(String(200))
    snelstart_machtiging_id: Mapped[str | None] = mapped_column(String(40))
    umr: Mapped[str | None] = mapped_column(String(35))
    outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    patched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SnelstartMachtigingMap(Base):
    """Per signed_mandate: welke Snelstart-machtiging hebben we gekoppeld?

    Voorkomt dat we per sync opnieuw een machtiging proberen aan te maken
    bij Snelstart. Eerste sync maakt 'm, volgende sync hergebruikt.
    """

    __tablename__ = "snelstart_machtiging_map"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "snelstart_machtiging_id",
            name="uq_snelstart_machtiging_id",
        ),
        UniqueConstraint(
            "org_id", "signed_mandate_id",
            name="uq_snelstart_machtiging_per_mandate",
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    signed_mandate_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("signed_mandates.id", ondelete="CASCADE"),
        nullable=False,
    )
    snelstart_relatie_id: Mapped[str] = mapped_column(String(40), nullable=False)
    snelstart_machtiging_id: Mapped[str] = mapped_column(String(40), nullable=False)
    umr: Mapped[str] = mapped_column(String(35), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
