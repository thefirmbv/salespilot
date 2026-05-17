"""UniFi state poller.

Runs every poll_interval_seconds (default 120s). For one org:
  1. fetch /ea/hosts, /ea/sites, /ea/devices in three API calls
  2. upsert each host / site / device into postgres
  3. detect state transitions (online <-> offline) and log them in
     unifi_state_events for the incidents feed + Grafana
  4. update last_polled timestamps

Idempotent: re-running is safe. State events are only written when the
new status differs from the previously stored status.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from salespilot.integrations.unifi import UniFiClient, UniFiError
from salespilot.models.unifi import (
    UnifiDevice, UnifiHost, UnifiSite, UnifiStateEvent,
)


def _parse_iso(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _host_is_online(host_raw: dict[str, Any]) -> bool:
    """A host is 'online' if any of its consoleGroupMembers report
    connectedState=CONNECTED. Falls back to !isBlocked when membership
    data is missing."""
    user_data = host_raw.get("userData") or {}
    members = user_data.get("consoleGroupMembers") or []
    if members:
        return any(
            (m.get("roleAttributes") or {}).get("connectedState") == "CONNECTED"
            for m in members
        )
    return not host_raw.get("isBlocked", False)


def _host_model_short(host_raw: dict[str, Any]) -> str | None:
    user_data = host_raw.get("userData") or {}
    hw = host_raw.get("hardware") or user_data.get("hardware") or {}
    return hw.get("shortname") or hw.get("name")


async def poll_unifi_for_org(
    db: AsyncSession,
    *,
    org_id: UUID,
    client: UniFiClient,
) -> dict[str, Any]:
    """Pull current state from api.ui.com and merge into postgres.

    Returns a counters dict:
      {
        "hosts_seen": int, "hosts_new": int,
        "sites_seen": int, "sites_new": int,
        "devices_seen": int, "devices_new": int,
        "state_events": int, "polled_at": iso,
      }
    """
    polled_at = datetime.now(UTC)

    hosts_raw = await client.list_hosts()
    sites_raw = await client.list_sites()
    devices_raw = await client.list_devices()

    # ------------------------------------------------------------------
    # Hosts
    # ------------------------------------------------------------------
    hosts_by_ubnt: dict[str, UnifiHost] = {}
    for h in (
        await db.execute(select(UnifiHost))
    ).scalars():
        hosts_by_ubnt[h.ubnt_host_id] = h

    hosts_new = 0
    state_events = 0
    for raw in hosts_raw:
        ubnt_id = raw.get("id")
        if not ubnt_id:
            continue
        user_data = raw.get("userData") or {}
        is_online = _host_is_online(raw)
        existing = hosts_by_ubnt.get(ubnt_id)
        if existing is None:
            existing = UnifiHost(
                id=uuid4(),
                org_id=org_id,
                ubnt_host_id=ubnt_id,
            )
            db.add(existing)
            hosts_new += 1
            hosts_by_ubnt[ubnt_id] = existing
            previous_status = None
        else:
            previous_status = "online" if existing.is_online else "offline"

        # Detect host-level state change
        new_status = "online" if is_online else "offline"
        if previous_status is not None and previous_status != new_status:
            db.add(UnifiStateEvent(
                id=uuid4(),
                org_id=org_id,
                entity_kind="host",
                entity_id=existing.id,
                previous_status=previous_status,
                new_status=new_status,
                occurred_at=polled_at,
                snapshot={"name": existing.name, "model_short": existing.model_short},
            ))
            state_events += 1
            existing.last_connection_change = polled_at

        existing.hardware_id = raw.get("hardwareId")
        # Host name lives in reportedState.hostname (preferred) or
        # reportedState.name. userData.fullName is the OWNER'S name (e.g.
        # Max Holtrop), not the device hostname, so we ignore it as a
        # source for our 'name' field but keep it as owner-context.
        reported = raw.get("reportedState") or {}
        existing.name = (
            reported.get("hostname") or reported.get("name")
            or raw.get("hostname") or existing.name or ""
        )[:255]
        existing.ip_address = raw.get("ipAddress")
        existing.owner_email = user_data.get("email")
        existing.model_short = (
            reported.get("hardware", {}).get("shortname")
            or _host_model_short(raw)
        )
        # Firmware version on consoles is reported under reportedState
        existing.firmware_version = (
            reported.get("version") or reported.get("firmwareVersion")
        )
        existing.model = reported.get("hardware", {}).get("name") or existing.model
        existing.is_blocked = bool(raw.get("isBlocked", False))
        existing.is_online = is_online
        existing.last_connection_change = (
            _parse_iso(raw.get("lastConnectionStateChange"))
            or existing.last_connection_change
        )
        existing.registration_time = (
            _parse_iso(raw.get("registrationTime"))
            or existing.registration_time
        )
        existing.last_polled = polled_at
        existing.raw = raw

    await db.flush()

    # ------------------------------------------------------------------
    # Sites
    # ------------------------------------------------------------------
    sites_by_ubnt: dict[str, UnifiSite] = {
        s.ubnt_site_id: s for s in (await db.execute(select(UnifiSite))).scalars()
    }
    sites_new = 0
    for raw in sites_raw:
        ubnt_id = raw.get("siteId") or raw.get("id")
        if not ubnt_id:
            continue
        host_ubnt = raw.get("hostId")
        host_row = hosts_by_ubnt.get(host_ubnt) if host_ubnt else None
        meta = raw.get("meta") or {}
        stats = raw.get("statistics") or {}
        counts = stats.get("counts") or {}

        existing = sites_by_ubnt.get(ubnt_id)
        if existing is None:
            existing = UnifiSite(
                id=uuid4(),
                org_id=org_id,
                ubnt_site_id=ubnt_id,
            )
            db.add(existing)
            sites_new += 1
            sites_by_ubnt[ubnt_id] = existing

        existing.host_id = host_row.id if host_row else None
        existing.name = (meta.get("name") or "default")[:120]
        existing.description = (meta.get("desc") or "")[:255] or None
        existing.gateway_mac = meta.get("gatewayMac")
        existing.timezone = meta.get("timezone")
        existing.total_devices = int(counts.get("totalDevice") or 0)
        existing.offline_devices = int(counts.get("offlineDevice") or 0)
        existing.wifi_clients = int(counts.get("wifiClient") or 0)
        existing.wired_clients = int(counts.get("wiredClient") or 0)
        existing.guest_clients = int(counts.get("guestClient") or 0)
        existing.critical_notifications = int(counts.get("criticalNotification") or 0)
        existing.raw = raw

    await db.flush()

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------
    devices_by_ubnt: dict[str, UnifiDevice] = {
        d.ubnt_device_id: d for d in (await db.execute(select(UnifiDevice))).scalars()
    }
    devices_new = 0
    devices_seen = 0
    for host_group in devices_raw:
        host_ubnt = host_group.get("hostId")
        host_row = hosts_by_ubnt.get(host_ubnt) if host_ubnt else None
        if host_row is None:
            # Device under a host we don't know -- skip until next host
            # poll catches up
            continue
        for dev in host_group.get("devices", []):
            ubnt_dev = dev.get("id") or dev.get("mac")
            if not ubnt_dev:
                continue
            devices_seen += 1
            existing = devices_by_ubnt.get(ubnt_dev)
            previous_status = existing.status if existing else None
            new_status = dev.get("status") or "unknown"

            if existing is None:
                existing = UnifiDevice(
                    id=uuid4(),
                    org_id=org_id,
                    ubnt_device_id=ubnt_dev,
                )
                db.add(existing)
                devices_new += 1
                devices_by_ubnt[ubnt_dev] = existing

            if previous_status is not None and previous_status != new_status:
                db.add(UnifiStateEvent(
                    id=uuid4(),
                    org_id=org_id,
                    entity_kind="device",
                    entity_id=existing.id,
                    previous_status=previous_status,
                    new_status=new_status,
                    occurred_at=polled_at,
                    snapshot={
                        "name": existing.name,
                        "model_short": existing.model_short,
                        "host_id": str(host_row.id),
                    },
                ))
                state_events += 1
                existing.last_status_change = polled_at

            existing.host_id = host_row.id
            existing.mac = dev.get("mac")
            existing.name = (dev.get("name") or "")[:255]
            existing.model = (dev.get("model") or "")[:64] or None
            existing.model_short = (dev.get("shortname") or "")[:32] or None
            existing.product_line = (dev.get("productLine") or "")[:32] or None
            existing.ip_address = dev.get("ip")
            existing.firmware_version = (dev.get("version") or "")[:64] or None
            existing.firmware_status = (dev.get("firmwareStatus") or "")[:32] or None
            existing.update_available = (dev.get("updateAvailable") or "")[:64] or None
            existing.is_console = bool(dev.get("isConsole", False))
            existing.is_managed = bool(dev.get("isManaged", True))
            existing.status = new_status
            existing.startup_time = _parse_iso(dev.get("startupTime"))
            existing.note = dev.get("note") or None
            existing.last_polled = polled_at
            existing.raw = dev

    await db.flush()

    return {
        "hosts_seen": len(hosts_raw),
        "hosts_new": hosts_new,
        "sites_seen": len(sites_raw),
        "sites_new": sites_new,
        "devices_seen": devices_seen,
        "devices_new": devices_new,
        "state_events": state_events,
        "polled_at": polled_at.isoformat(),
    }
