"""Signed SEPA mandate table.

Stores every submitted SEPA direct-debit mandate from sign.it-gemak.nl.
NOT tenant-scoped via RLS because submissions come from the public web
without authentication; instead we hard-pin them to the IT-gemak org_id
at insert-time (since this portal is exclusively for IT-gemak).

The PDF is generated server-side at submission time, hashed (SHA-256),
and stored on disk; the hash lives in the row for legal integrity.

Revision ID: 0012_signed_mandates
Revises: 0011_activity_extras
Create Date: 2026-05-13
"""

from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "0012_signed_mandates"
down_revision: Union[str, None] = "0011_activity_extras"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signed_mandates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        # SEPA Unique Mandate Reference (UMR) — visible on every direct
        # debit collection. We generate a short, customer-friendly ID like
        # ITG-2026-A7B3.
        sa.Column("umr", sa.String(35), nullable=False, unique=True),

        # Debiteur (NAW)
        sa.Column("debtor_name", sa.String(200), nullable=False),
        sa.Column("debtor_address", sa.String(255), nullable=False),
        sa.Column("debtor_postcode", sa.String(20), nullable=False),
        sa.Column("debtor_city", sa.String(120), nullable=False),
        sa.Column("debtor_country", sa.String(80), nullable=False, server_default="Nederland"),
        sa.Column("debtor_iban", sa.String(34), nullable=False),
        sa.Column("debtor_bic", sa.String(11), nullable=True),
        sa.Column("debtor_email", sa.String(255), nullable=False),
        sa.Column("debtor_phone", sa.String(40), nullable=True),
        sa.Column("debtor_kvk", sa.String(20), nullable=True),

        # Place + signature
        sa.Column("sign_place", sa.String(120), nullable=False),
        # Base64-encoded PNG of the canvas signature
        sa.Column("signature_png_base64", sa.Text(), nullable=False),

        # Audit trail
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("geo_country", sa.String(80), nullable=True),
        sa.Column("geo_region", sa.String(80), nullable=True),
        sa.Column("geo_city", sa.String(120), nullable=True),
        sa.Column("geo_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("geo_lon", sa.Numeric(9, 6), nullable=True),

        # KvK verification (optional — only set when KvK lookup succeeded)
        sa.Column("kvk_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("kvk_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kvk_raw", postgresql.JSONB, nullable=True),

        # Integrity
        sa.Column("pdf_path", sa.String(500), nullable=True),
        sa.Column("pdf_sha256", sa.String(64), nullable=True),

        # Workflow state
        sa.Column("status", sa.String(20), nullable=False, server_default="submitted"),
        # submitted | emailed | failed | revoked
        sa.Column("emailed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_error", sa.Text(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_signed_mandates_created_at",
        "signed_mandates",
        ["created_at"],
    )
    op.create_index(
        "ix_signed_mandates_debtor_email",
        "signed_mandates",
        ["debtor_email"],
    )


def downgrade() -> None:
    op.drop_index("ix_signed_mandates_debtor_email", table_name="signed_mandates")
    op.drop_index("ix_signed_mandates_created_at", table_name="signed_mandates")
    op.drop_table("signed_mandates")
