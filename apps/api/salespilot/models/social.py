"""SQLAlchemy models for the social-content scheduler.

A social_post represents one piece of content the marketing team is
preparing. It can target one or more destinations (e.g. personal LinkedIn
+ company page in one go). Media attachments live in social_post_media.
Metrics are pulled on a cadence and stored in social_post_metrics so we
can chart change over time.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from salespilot.models import Base, TenantScoped, Timestamps, UUIDPrimaryKey


class SocialPost(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    __tablename__ = "social_posts"

    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    destinations: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    title: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_result: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class SocialPostMedia(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    __tablename__ = "social_post_media"

    post_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("social_posts.id", ondelete="CASCADE")
    )
    uploaded_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    alt_text: Mapped[str | None] = mapped_column(String(500))
    caption: Mapped[str | None] = mapped_column(String(500))
    linkedin_asset_urn: Mapped[str | None] = mapped_column(String(200))


class SocialPostMetrics(UUIDPrimaryKey, TenantScoped, Base):
    """One snapshot of analytics for one (post, destination) pair.

    We don't inherit Timestamps because snapshot_at IS the timestamp.
    """

    __tablename__ = "social_post_metrics"

    post_id: Mapped[UUID] = mapped_column(
        ForeignKey("social_posts.id", ondelete="CASCADE"), nullable=False
    )
    platform_post_id: Mapped[str] = mapped_column(String(200), nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unique_impressions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    likes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    comments: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shares: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    engagement_rate: Mapped[float | None] = mapped_column(Float)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
