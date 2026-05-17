"""Hosting + domain management models.

Two integrations live in this file because they're closely related
(Plesk hosting + Openprovider domain registration). Both follow the
UniFi pattern: poll cloud, mirror to postgres, manual klant-link,
sync as HaloPSA Asset for recurring billing.

Tables:
    plesk_subscriptions    -- one row per Plesk hosting subscription
                              (the billable unit, qty=1 per asset)
    plesk_domains          -- domains under a subscription
    plesk_state_events     -- subscription enable/disable transitions
    plesk_company_links    -- subscription -> SalesPilot company

    openprovider_domains   -- registered domains (one asset per row)
    openprovider_company_links -- domain -> SalesPilot company
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from salespilot.models import Base, TenantScoped, Timestamps, UUIDPrimaryKey


# ======================================================================
# Plesk
# ======================================================================


class PleskServer(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    """One Plesk server. Multiple servers can run per org (4-5 is common
    for a hosting reseller). Each server has its own URL + API key.
    The integration row 'plesk' holds shared defaults (asset_type,
    halopsa_product_id, poll_interval); this table holds per-server
    credentials."""
    __tablename__ = "plesk_servers"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str | None] = mapped_column(String(32))
    last_sync_message: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_plesk_servers_org_name"),
    )


class PleskSubscription(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    """One Plesk hosting subscription = one billable asset."""
    __tablename__ = "plesk_subscriptions"

    plesk_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    server_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("plesk_servers.id", ondelete="SET NULL"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), default="")
    main_domain: Mapped[str | None] = mapped_column(String(255), index=True)
    owner_login: Mapped[str | None] = mapped_column(String(120))
    owner_email: Mapped[str | None] = mapped_column(String(255))
    plan_name: Mapped[str | None] = mapped_column(String(120))
    plan_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="active")  # active|suspended|disabled
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    disk_used_mb: Mapped[int] = mapped_column(Integer, default=0)
    disk_limit_mb: Mapped[int | None] = mapped_column(Integer)
    traffic_used_mb: Mapped[int] = mapped_column(Integer, default=0)
    mailboxes_count: Mapped[int] = mapped_column(Integer, default=0)
    databases_count: Mapped[int] = mapped_column(Integer, default=0)
    created_in_plesk: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # HaloPSA link
    halopsa_asset_id: Mapped[int | None] = mapped_column(Integer, index=True)
    halopsa_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Poll
    last_polled: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status_change: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "plesk_id", name="uq_plesk_subs_org_pid"),
        Index("ix_plesk_subs_org_status", "org_id", "status"),
        Index("ix_plesk_subs_halopsa_asset_id", "halopsa_asset_id"),
    )


class PleskDomain(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    """A domain under a Plesk subscription. Reference only; the
    subscription is the billable asset."""
    __tablename__ = "plesk_domains"

    plesk_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    server_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("plesk_servers.id", ondelete="SET NULL"),
    )
    subscription_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("plesk_subscriptions.id", ondelete="CASCADE"),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    type: Mapped[str | None] = mapped_column(String(32))  # primary|addon|parked|alias
    status: Mapped[str] = mapped_column(String(32), default="active")
    ssl_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_polled: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "plesk_id", name="uq_plesk_domains_org_pid"),
    )


class PleskStateEvent(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    """Subscription state transitions (active <-> suspended <-> disabled)."""
    __tablename__ = "plesk_state_events"

    subscription_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("plesk_subscriptions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    previous_status: Mapped[str | None] = mapped_column(String(32))
    new_status: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_plesk_state_events_occurred", "org_id", "occurred_at"),
    )


class PleskCompanyLink(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    """Plesk subscription -> SalesPilot company for billing."""
    __tablename__ = "plesk_company_links"

    subscription_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("plesk_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    halopsa_product_id: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("org_id", "subscription_id",
                         name="uq_plesk_links_subscription"),
    )


# ======================================================================
# Openprovider
# ======================================================================


class OpenproviderDomain(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    """One registered domain at Openprovider = one billable asset."""
    __tablename__ = "openprovider_domains"

    op_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    extension: Mapped[str | None] = mapped_column(String(16))   # .nl, .com, ...
    status: Mapped[str] = mapped_column(String(32), default="active")
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True)
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    nameservers: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    owner_handle: Mapped[str | None] = mapped_column(String(120))
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    # HaloPSA link
    halopsa_asset_id: Mapped[int | None] = mapped_column(Integer, index=True)
    halopsa_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_polled: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "op_id", name="uq_op_domains_org_opid"),
        Index("ix_op_domains_org_status", "org_id", "status"),
        Index("ix_op_domains_expires", "org_id", "expires_at"),
    )


class OpenproviderCompanyLink(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    """Openprovider domain -> SalesPilot company for billing."""
    __tablename__ = "openprovider_company_links"

    domain_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("openprovider_domains.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    halopsa_product_id: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("org_id", "domain_id",
                         name="uq_op_links_domain"),
    )



# ======================================================================
# Openprovider audit log -- domain register/cancel/auto_renew_change
# ======================================================================


class OpenproviderAuditLog(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    """Every write-action against Openprovider is logged here.

    Why: registrations cost real money and cancellations are
    time-bound. We need a paper trail for who did what, with the
    Openprovider response captured for debugging failures.
    """
    __tablename__ = "openprovider_audit_log"

    user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    # register | cancel | auto_renew_on | auto_renew_off | nameserver_change
    domain_name: Mapped[str | None] = mapped_column(String(255))
    domain_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("openprovider_domains.id", ondelete="SET NULL"),
    )
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok|error
    request_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    response_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
