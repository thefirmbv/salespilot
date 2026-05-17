"""UniFi -> HaloPSA asset sync.

For every UniFi device that is linked to a SalesPilot company (via
unifi_company_links host -> company), upsert a HaloPSA Asset:

    name        = unifi_device.name (or '<host>: <model>' fallback)
    type        = "UniFi Devices" (or whatever Integration.config_json.asset_type says)
    client_id   = HaloPSA client linked to that company
    key_field_1 = mac address (unique identifier for re-matching)
    field_x     = model_short, firmware_version, ip_address, host_name

Idempotent: matches existing assets on key_field_1 == mac before
creating a new one. Records halopsa_asset_id back on unifi_devices.

REQUIRES SCOPE: read:assets edit:assets on the HaloPSA application.
Without these, the call to /api/Asset returns 403.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from salespilot.integrations.halopsa import HaloPSAClient, HaloPSAError
from salespilot.models.crm import Company
from salespilot.models.unifi import (
    UnifiCompanyLink, UnifiDevice, UnifiHost,
)


async def _ensure_asset_type(client: HaloPSAClient, type_name: str) -> int | None:
    """Find or create the 'UniFi Devices' AssetType in HaloPSA.

    Returns the type id. Returns None if 403 (caller will surface the
    scope problem to the user).
    """
    try:
        data = await client._request("GET", "/api/AssetType")
    except HaloPSAError as e:
        if "403" in str(e):
            return None
        raise
    items = data if isinstance(data, list) else (data.get("asset_types") or data.get("results") or [])
    for t in items:
        if (t.get("name") or "").lower() == type_name.lower():
            return int(t["id"])
    # Create it
    try:
        created = await client._request(
            "POST", "/api/AssetType",
            json=[{"name": type_name, "active": True}],
        )
    except HaloPSAError:
        return None
    if isinstance(created, list) and created:
        return int(created[0].get("id"))
    if isinstance(created, dict) and created.get("id"):
        return int(created["id"])
    return None


def _device_to_asset_payload(
    device: UnifiDevice, host: UnifiHost,
    halopsa_client_id: int, asset_type_id: int,
) -> dict[str, Any]:
    """Build a HaloPSA Asset payload from one UniFi device."""
    return {
        "inventory_number": device.mac or device.ubnt_device_id,
        "key_field": device.mac or device.ubnt_device_id,
        "key_field2": device.model_short or "",
        "key_field3": device.firmware_version or "",
        "name": device.name or f"{host.name}: {device.model_short or 'UniFi device'}",
        "assettype_id": asset_type_id,
        "client_id": halopsa_client_id,
        "fields": [
            {"name": "Model", "value": device.model or device.model_short or ""},
            {"name": "MAC", "value": device.mac or ""},
            {"name": "IP", "value": device.ip_address or ""},
            {"name": "Firmware", "value": device.firmware_version or ""},
            {"name": "Host", "value": host.name or ""},
            {"name": "UniFi host id", "value": host.ubnt_host_id},
            {"name": "Status", "value": device.status},
        ],
    }


async def _find_existing_asset(
    client: HaloPSAClient, mac: str, asset_type_id: int,
) -> int | None:
    """Look up an existing HaloPSA Asset by MAC (we stored it in
    inventory_number + key_field)."""
    try:
        data = await client._request(
            "GET", "/api/Asset",
            params={"search": mac, "assettype_id": asset_type_id, "count": 5},
        )
    except HaloPSAError:
        return None
    items = data if isinstance(data, list) else (data.get("assets") or [])
    for a in items:
        if (a.get("key_field") or a.get("inventory_number") or "").lower() == mac.lower():
            return int(a["id"])
    return None


async def sync_unifi_devices_to_halopsa(
    db: AsyncSession,
    *,
    org_id: UUID,
    halopsa_client: HaloPSAClient,
    asset_type_name: str = "UniFi Devices",
    company_id: UUID | None = None,
) -> dict[str, Any]:
    """Mirror linked UniFi devices into HaloPSA assets.

    Iterates over unifi_company_links and for each host's devices upserts
    a HaloPSA Asset under the linked HaloPSA client (= company.halopsa_id).
    If ``company_id`` is given, only that one company's hosts are synced.

    Returns counts: { hosts_processed, devices_upserted, devices_created,
                      devices_updated, errors }
    """
    asset_type_id = await _ensure_asset_type(halopsa_client, asset_type_name)
    if asset_type_id is None:
        return {
            "ok": False,
            "detail": (
                "HaloPSA gaf 403 op /api/AssetType. Voeg in HaloPSA admin de "
                "scopes 'read:assets edit:assets' toe aan onze applicatie."
            ),
            "hosts_processed": 0,
            "devices_upserted": 0,
            "devices_created": 0,
            "devices_updated": 0,
            "errors": [],
        }

    q = select(UnifiCompanyLink, UnifiHost, Company).join(
        UnifiHost, UnifiHost.id == UnifiCompanyLink.host_id,
    ).join(
        Company, Company.id == UnifiCompanyLink.company_id,
    )
    if company_id is not None:
        q = q.where(UnifiCompanyLink.company_id == company_id)
    triples = (await db.execute(q)).all()

    hosts_processed = 0
    devices_created = 0
    devices_updated = 0
    errors: list[dict[str, Any]] = []

    for link, host, company in triples:
        hosts_processed += 1
        halopsa_client_id = getattr(company, "halopsa_id", None)
        if not halopsa_client_id:
            errors.append({
                "host": host.name,
                "company": company.name,
                "error": "Company is not linked to a HaloPSA client (halopsa_id missing).",
            })
            continue

        devices = (
            await db.execute(
                select(UnifiDevice).where(UnifiDevice.host_id == host.id)
            )
        ).scalars().all()

        for dev in devices:
            mac = dev.mac or dev.ubnt_device_id
            if not mac:
                continue
            payload = _device_to_asset_payload(
                dev, host, halopsa_client_id, asset_type_id,
            )
            try:
                if dev.halopsa_asset_id:
                    # Update existing
                    payload["id"] = dev.halopsa_asset_id
                    await halopsa_client._request("POST", "/api/Asset", json=[payload])
                    devices_updated += 1
                else:
                    # Look up first by MAC
                    existing_id = await _find_existing_asset(
                        halopsa_client, mac, asset_type_id,
                    )
                    if existing_id:
                        payload["id"] = existing_id
                        await halopsa_client._request("POST", "/api/Asset", json=[payload])
                        dev.halopsa_asset_id = existing_id
                        devices_updated += 1
                    else:
                        created = await halopsa_client._request(
                            "POST", "/api/Asset", json=[payload],
                        )
                        new_id = None
                        if isinstance(created, list) and created:
                            new_id = created[0].get("id")
                        elif isinstance(created, dict):
                            new_id = created.get("id")
                        if new_id:
                            dev.halopsa_asset_id = int(new_id)
                            devices_created += 1
                dev.halopsa_synced_at = datetime.now(UTC)
            except HaloPSAError as e:
                errors.append({
                    "host": host.name, "device": dev.name, "mac": mac,
                    "error": str(e)[:200],
                })

    await db.flush()

    return {
        "ok": True,
        "asset_type_id": asset_type_id,
        "hosts_processed": hosts_processed,
        "devices_upserted": devices_created + devices_updated,
        "devices_created": devices_created,
        "devices_updated": devices_updated,
        "errors": errors,
    }
