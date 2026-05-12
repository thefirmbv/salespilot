"""Wespennest — acquisition pipeline for clients of acquired Dutch MSPs.

The idea: when an MSP gets bought by a PE-roll-up, their existing customers
typically face service-focus shifts within 6-12 months. We want to identify
those customers BEFORE the cracks show and reach out with a tailored pitch.

The data layer captures:
  * MSPs and their acquisition events
  * Fingerprints to attribute domains -> MSP (NS, SPF, support-CNAME, etc.)
  * Discovered domains + per-scan signals (M365, mail, web)
  * KVK-enriched companies behind those domains
  * Decision-makers per company (DGA / IT manager) with verified emails
  * The lead-candidates view = the bell-list

Revision ID: 0008_wespennest
Revises: 0007_mail_campaigns
Create Date: 2026-05-12
"""

from typing import Union
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008_wespennest"
down_revision: Union[str, None] = "0007_mail_campaigns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ----- MSPs and their acquisitions -----
    op.create_table(
        "wn_msps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kvk_number", sa.String(8), nullable=True),
        sa.Column("website", sa.String(200), nullable=True),
        # The acquiring entity (e.g. "TSH", "Solimas Groep", "Your.Cloud")
        sa.Column("acquired_by", sa.String(200), nullable=True),
        sa.Column("acquired_date", sa.Date(), nullable=True),
        sa.Column("investor", sa.String(200), nullable=True),
        sa.Column("region", sa.String(120), nullable=True),
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        # Flag so we can hide deprecated/incorrect entries without deleting
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_wn_msps_org", "wn_msps", ["org_id", "is_active"])
    _rls("wn_msps")

    # ----- Fingerprints used to attribute domains to an MSP -----
    op.create_table(
        "wn_msp_fingerprints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("msp_id", postgresql.UUID(as_uuid=True), nullable=False),
        # 'ns', 'spf_include', 'cname_support', 'soa_rname', 'cert_san', 'website'
        sa.Column("signal_type", sa.String(40), nullable=False),
        sa.Column("pattern", sa.String(500), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["msp_id"], ["wn_msps.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_wn_fingerprints_msp", "wn_msp_fingerprints", ["org_id", "msp_id"])
    _rls("wn_msp_fingerprints")

    # ----- Discovered domains -----
    op.create_table(
        "wn_domains",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        # crt.sh / seedlist / manual / overname_announcement
        sa.Column("discovery_source", sa.String(40), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_scanned", sa.DateTime(timezone=True), nullable=True),
        # Status of the per-domain scan pipeline:
        #   'pending'   = newly discovered, nothing scanned yet
        #   'scanning'  = worker picked it up
        #   'scanned'   = all signals collected
        #   'enriched'  = KVK + geocode + decision-maker done
        #   'qualified' = passed lead filter (in lead_candidates view)
        #   'rejected'  = didn't pass filter (no M365, too far, wrong size, etc.)
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("org_id", "domain", name="uq_wn_domains_domain"),
    )
    op.create_index("ix_wn_domains_status", "wn_domains", ["org_id", "status"])
    _rls("wn_domains")

    # ----- Per-domain scan signals -----
    op.create_table(
        "wn_domain_signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dns", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("m365", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("mail", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("web", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["domain_id"], ["wn_domains.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_wn_signals_domain", "wn_domain_signals", ["org_id", "domain_id"])
    _rls("wn_domain_signals")

    # ----- Vendor attribution (which MSP "owns" this domain right now) -----
    op.create_table(
        "wn_vendor_attribution",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("msp_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("rules_fired", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("attributed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["domain_id"], ["wn_domains.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["msp_id"], ["wn_msps.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("org_id", "domain_id", "msp_id", name="uq_wn_attribution"),
    )
    op.create_index("ix_wn_attribution_msp", "wn_vendor_attribution", ["org_id", "msp_id"])
    _rls("wn_vendor_attribution")

    # ----- KVK-enriched companies behind the domains -----
    op.create_table(
        "wn_kvk_companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kvk_nummer", sa.String(8), nullable=False),
        sa.Column("handelsnaam", sa.String(300), nullable=True),
        sa.Column("rechtsvorm", sa.String(80), nullable=True),
        sa.Column("sbi_codes", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("werkzame_personen", sa.Integer(), nullable=True),
        sa.Column("grootteklasse", sa.String(8), nullable=True),
        sa.Column("adres", sa.String(300), nullable=True),
        sa.Column("postcode", sa.String(8), nullable=True),
        sa.Column("plaats", sa.String(120), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        # Distance to Breukelen (org HQ) — cached for filter performance
        sa.Column("km_to_hq", sa.Float(), nullable=True),
        sa.Column("telefoon", sa.String(40), nullable=True),
        sa.Column("nis2_sector", sa.String(80), nullable=True),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("org_id", "kvk_nummer", name="uq_wn_kvk_nummer"),
    )
    op.create_index("ix_wn_kvk_size", "wn_kvk_companies", ["org_id", "werkzame_personen"])
    op.create_index("ix_wn_kvk_distance", "wn_kvk_companies", ["org_id", "km_to_hq"])
    _rls("wn_kvk_companies")

    # ----- Domain <-> KVK company link (a domain may belong to one company) -----
    op.create_table(
        "wn_domain_kvk",
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kvk_company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["domain_id"], ["wn_domains.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["kvk_company_id"], ["wn_kvk_companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id", "domain_id", "kvk_company_id"),
    )
    _rls("wn_domain_kvk")

    # ----- Decision-makers per KVK company -----
    op.create_table(
        "wn_decision_makers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kvk_company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("voornaam", sa.String(120), nullable=True),
        sa.Column("tussenvoegsel", sa.String(40), nullable=True),
        sa.Column("achternaam", sa.String(120), nullable=True),
        sa.Column("functie", sa.String(120), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        # 'verified' = SMTP 250, 'unverified' = no probe yet, 'invalid' = 550,
        # 'unknown' = catch-all/greylist
        sa.Column("email_verified", sa.String(20), nullable=False, server_default="unverified"),
        sa.Column("email_verify_method", sa.String(40), nullable=True),
        sa.Column("email_pattern_used", sa.String(80), nullable=True),
        sa.Column("telefoon", sa.String(40), nullable=True),
        sa.Column("linkedin_url", sa.String(300), nullable=True),
        sa.Column("source", sa.String(40), nullable=True),
        # Optional link to a SalesPilot contact once converted
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["kvk_company_id"], ["wn_kvk_companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_wn_dm_company", "wn_decision_makers", ["org_id", "kvk_company_id"])
    op.create_index("ix_wn_dm_email", "wn_decision_makers", ["org_id", "email"])
    _rls("wn_decision_makers")

    # ----- Acquisition news feed -----
    op.create_table(
        "wn_acquisition_signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        # 'computable', 'dutch_it_channel', 'mena', 'emerce', 'manual'
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("source_url", sa.String(500), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        # 'new' = unreviewed; 'confirmed' = verified, MSP added;
        # 'rejected' = not relevant; 'duplicate' = same as earlier signal
        sa.Column("status", sa.String(20), nullable=False, server_default="new"),
        sa.Column("matched_keywords", postgresql.ARRAY(sa.String()), nullable=True),
        # Optional fields filled when reviewed
        sa.Column("msp_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["msp_id"], ["wn_msps.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_wn_signals_status", "wn_acquisition_signals", ["org_id", "status"])
    op.create_index("ix_wn_signals_published", "wn_acquisition_signals", ["org_id", "published_at"])
    _rls("wn_acquisition_signals")

    # ----- Pipeline job status tracking -----
    # One row per pipeline-job-kind so the UI can show "last run / status / next run".
    op.create_table(
        "wn_pipeline_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        # 'overname_monitor' | 'domain_discovery' | 'm365_scanner' |
        # 'msp_fingerprint' | 'kvk_geofilter' | 'decision_maker_finder' |
        # 'email_verify' | 'full_pipeline'
        sa.Column("job_kind", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),  # running | success | failed
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("items_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_wn_pipeline_runs_kind", "wn_pipeline_runs",
        ["org_id", "job_kind", "started_at"],
    )
    _rls("wn_pipeline_runs")


def _rls(table_name: str) -> None:
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table_name}
        USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
        WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table_name} TO salespilot_app")


def downgrade() -> None:
    for t in (
        "wn_pipeline_runs",
        "wn_acquisition_signals",
        "wn_decision_makers",
        "wn_domain_kvk",
        "wn_kvk_companies",
        "wn_vendor_attribution",
        "wn_domain_signals",
        "wn_domains",
        "wn_msp_fingerprints",
        "wn_msps",
    ):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {t}")
        op.drop_table(t)
