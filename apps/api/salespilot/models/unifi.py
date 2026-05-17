"""UniFi monitoring models.

We mirror the UniFi cloud state into Postgres so the dashboard /
incidents / device-count queries are fast (no live API calls per
request). The poller (integrations.unifi_poller) keeps these in sync.

Five tables:
  unifi_hosts            -- one row per UniFi console (UDM, UDM-Pro, UCG, ...)
  unifi_sites            -- network sites under a host (= 'default' or named)
  unifi_devices          -- APs, switches, cameras, etc. (any managed device)
  unifi_state_events     -- state transition log: online <-> offline
  unifi_company_links    -- maps host_id -> SalesPilot company_id for billing

All tenant-scoped via TenantScoped mixin so RLS applies.
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


class UnifiHost(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    """A UniFi console (Dream Machine / UCG / UDR)."""
    __tablename__ = "unifi_hosts"

    # Ubiquiti's host id is a long opaque string (digest:bigint shape)
    ubnt_host_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    hardware_id: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255), default="")
    ip_address: Mapped[str | None] = mapped_column(String(64))
    owner_email: Mapped[str | None] = mapped_column(String(255))
    model: Mapped[str | None] = mapped_column(String(64))
    model_short: Mapped[str | None] = mapped_column(String(32))
    firmware_version: Mapped[str | None] = mapped_column(String(64))
    # Status flags
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    last_connection_change: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registration_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Polling
    last_polled: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    devices: Mapped[list["UnifiDevice"]] = relationship(
        back_populates="host", cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("org_id", "ubnt_host_id", name="uq_unifi_hosts_org_ubnt"),
        Index("ix_unifi_hosts_online", "org_id", "is_online"),
    )


class UnifiSite(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    """A network site under a host. Most consoles have only 'default'."""
    __tablename__ = "unifi_sites"

    ubnt_site_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    host_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("unifi_hosts.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120), default="default")
    description: Mapped[str | None] = mapped_column(String(255))
    gateway_mac: Mapped[str | None] = mapped_column(String(32))
    timezone: Mapped[str | None] = mapped_column(String(64))
    # Counters (snapshot from /ea/sites statistics.counts)
    total_devices: Mapped[int] = mapped_column(Integer, default=0)
    offline_devices: Mapped[int] = mapped_column(Integer, default=0)
    wifi_clients: Mapped[int] = mapped_column(Integer, default=0)
    wired_clients: Mapped[int] = mapped_column(Integer, default=0)
    guest_clients: Mapped[int] = mapped_column(Integer, default=0)
    critical_notifications: Mapped[int] = mapped_column(Integer, default=0)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "ubnt_site_id", name="uq_unifi_sites_org_ubnt"),
    )


class UnifiDevice(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    """A managed UniFi device: AP, switch, camera, gateway, ..."""
    __tablename__ = "unifi_devices"

    # ubnt 'id' is usually the MAC without separators
    ubnt_device_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    host_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("unifi_hosts.id", ondelete="CASCADE"))
    mac: Mapped[str | None] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    model: Mapped[str | None] = mapped_column(String(64))
    model_short: Mapped[str | None] = mapped_column(String(32))
    product_line: Mapped[str | None] = mapped_column(String(32))  # network / protect / access / talk
    ip_address: Mapped[str | None] = mapped_column(String(64))
    firmware_version: Mapped[str | None] = mapped_column(String(64))
    firmware_status: Mapped[str | None] = mapped_column(String(32))  # upToDate | updateAvailable | ...
    update_available: Mapped[str | None] = mapped_column(String(64))
    is_console: Mapped[bool] = mapped_column(Boolean, default=False)
    is_managed: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(32), default="unknown")  # online | offline | adopting | ...
    startup_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    # HaloPSA asset link
    halopsa_asset_id: Mapped[int | None] = mapped_column(Integer, index=True)
    halopsa_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Polling
    last_polled: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status_change: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    host: Mapped["UnifiHost"] = relationship(back_populates="devices")

    __table_args__ = (
        UniqueConstraint("org_id", "ubnt_device_id", name="uq_unifi_devices_org_ubnt"),
        Index("ix_unifi_devices_host_status", "host_id", "status"),
        Index("ix_unifi_devices_org_status", "org_id", "status"),
    )


class UnifiStateEvent(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    """State transition: a device or host going online/offline.

    Written by the poller every time a state change is detected. Powers
    the incidents feed + Grafana downtime charts. Two granularities:
    entity_kind = 'host' or 'device'.
    """
    __tablename__ = "unifi_state_events"

    entity_kind: Mapped[str] = mapped_column(String(16), nullable=False)  # host | device
    entity_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    previous_status: Mapped[str | None] = mapped_column(String(32))
    new_status: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)  # how long previous_status lasted
    # Snapshot of identifying fields for read-only consumption (so the
    # incidents feed doesn't need a join):
    snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_unifi_state_events_occurred", "org_id", "occurred_at"),
        Index("ix_unifi_state_events_entity", "entity_kind", "entity_id"),
    )


class UnifiCompanyLink(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    """Maps a UniFi host (Dream Machine) to a SalesPilot company.

    Once linked, the host's device_count flows into HaloPSA invoice
    line `Aantal` for the recurring "UniFi monitoring" product.
    """
    __tablename__ = "unifi_company_links"

    host_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("unifi_hosts.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    # HaloPSA recurring invoice product id (the "UniFi devices" item)
    halopsa_product_id: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("org_id", "host_id", name="uq_unifi_company_links_host"),
    )
