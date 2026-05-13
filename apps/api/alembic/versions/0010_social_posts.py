"""LinkedIn content scheduler.

Adds three tables:

  social_posts          one row per post draft / scheduled / published.
                        Supports multi-destination (personal + company),
                        media via JSON, status timeline.

  social_post_media     uploaded images/videos. Stored on disk under
                        /opt/salespilot/data/social-media/. The DB row
                        keeps the relative path + metadata.

  social_post_metrics   periodic snapshots of LinkedIn analytics so we
                        can chart growth over time.

Architecture notes:
  * platform column is varchar so we can add x/facebook/instagram later
    without another migration.
  * destinations is a JSONB array of {platform, target_type, target_urn,
    target_name} so one post can be sent to multiple endpoints in one
    user action.
  * scheduled_at is null for drafts; set by the scheduler-worker logic.
  * status: draft | scheduled | publishing | published | failed | cancelled

Revision ID: 0010_social_posts
Revises: 0009_platform_admin
Create Date: 2026-05-13
"""

from typing import Union
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010_social_posts"
down_revision: Union[str, None] = "0009_platform_admin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "social_posts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        # The author chooses one or more destinations at publish time.
        # destinations example:
        #   [{"platform": "linkedin", "target_type": "person",
        #     "target_urn": "urn:li:person:XYZ", "target_name": "Jan Janssen"},
        #    {"platform": "linkedin", "target_type": "organization",
        #     "target_urn": "urn:li:organization:1234", "target_name": "IT-Gemak"}]
        sa.Column(
            "destinations",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        # Body of the post. LinkedIn allows up to 3000 chars per post.
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        # Lightweight title/internal label so the kalender + lijst kan
        # iets korters tonen dan de volledige body.
        sa.Column("title", sa.String(160), nullable=True),
        # 'draft' | 'scheduled' | 'publishing' | 'published' | 'failed' | 'cancelled'
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        # When the user wants this published (UTC). NULL for drafts.
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        # Filled in by the publisher when it actually went out.
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        # Per-destination publish results (URNs returned by LinkedIn,
        # post URLs, etc.). Shape mirrors destinations + adds platform_post_id,
        # post_url, published_at, error.
        sa.Column(
            "publish_result",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        # Last failure message, surfaced in the UI.
        sa.Column("last_error", sa.Text(), nullable=True),
        # When > 0 the publisher will retry up to N times spaced 5 min.
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_social_posts_status_sched",
        "social_posts",
        ["org_id", "status", "scheduled_at"],
    )
    op.create_index(
        "ix_social_posts_org_created",
        "social_posts",
        ["org_id", "created_at"],
    )
    _rls("social_posts")

    op.create_table(
        "social_post_media",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("post_id", postgresql.UUID(as_uuid=True), nullable=True),
        # If null, this is a stand-alone upload not yet attached to a post.
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), nullable=True),
        # Position within the post (carousel ordering).
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        # File metadata
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        # Relative path under /opt/salespilot/data/social-media/
        sa.Column("storage_path", sa.String(500), nullable=False),
        # Optional alt text for accessibility
        sa.Column("alt_text", sa.String(500), nullable=True),
        # Optional caption shown below carousel image
        sa.Column("caption", sa.String(500), nullable=True),
        # For pre-uploads to LinkedIn (initialiseUpload step) we cache the
        # asset URN so we don't re-upload when the user re-saves a draft.
        sa.Column("linkedin_asset_urn", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["post_id"], ["social_posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_social_media_post",
        "social_post_media",
        ["org_id", "post_id"],
    )
    _rls("social_post_media")

    op.create_table(
        "social_post_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("post_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Which destination's metrics this is for. Allows separate
        # tracking for person vs company posts.
        sa.Column("platform_post_id", sa.String(200), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unique_impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("likes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("comments", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shares", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("engagement_rate", sa.Float(), nullable=True),
        sa.Column(
            "raw",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["post_id"], ["social_posts.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_social_metrics_post_at",
        "social_post_metrics",
        ["org_id", "post_id", "snapshot_at"],
    )
    _rls("social_post_metrics")


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
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table_name} TO salespilot_app"
    )


def downgrade() -> None:
    for t in ("social_post_metrics", "social_post_media", "social_posts"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {t}")
        op.drop_table(t)
