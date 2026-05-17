"""Plesk + Openprovider → HaloPSA asset-sync.

Asset-strategie (per Jasper's specificatie):
  - AssetGroup: "Domeinnaam en Hosting" (id=124 in deze tenant)
  - AssetType: "Plesk Subscription" voor hosting, "Domain Registration"
    voor domeinen. Aangemaakt onder group 124 als ze niet bestaan.
  - 1 subscription = 1 asset, qty=1 op recurring factuurregel
  - 1 domein = 1 asset, qty=1
  - Asset.name = subscription.name of domain.name (zichtbaar in factuur)
  - Asset.item_id = halopsa_product_id (per asset eigen tarief mogelijk)
  - Asset.client_id = company.halopsa_id

Het 'asset_group_id' veld op een AssetType bepaalt onder welke group
het valt; assets erven die group automatisch via assettype_id.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from salespilot.integrations.halopsa import HaloPSAClient, HaloPSAError
from salespilot.models.crm import Company
from salespilot.models.hosting import (
    OpenproviderCompanyLink, OpenproviderDomain,
    PleskCompanyLink, PleskSubscription,
)


HOSTING_GROUP_NAME = "Domeinnaam en Hosting"
PLESK_TYPE_NAME = "Plesk Subscription"
OPENPROVIDER_TYPE_NAME = "Domain Registration"


async def _get_main_site_id(
    client: HaloPSAClient, halopsa_client_id: int,
) -> int | None:
    """Vind de Main-site van een HaloPSA client. Asset MOET aan een
    site hangen die bij de juiste client hoort, anders zet HaloPSA hem
    op 'Unknown' (client_id=1)."""
    try:
        d = await client._request(
            "GET", "/api/Site",
            params={"client_id": halopsa_client_id, "count": 10},
        )
    except HaloPSAError:
        return None
    items = d if isinstance(d, list) else (d.get("sites") or [])
    for s in items:
        if (s.get("name") or "").lower() == "main":
            return int(s["id"])
    if items:
        return int(items[0]["id"])
    return None


async def _ensure_assettype(
    client: HaloPSAClient, type_name: str, group_name: str,
) -> int | None:
    """Vind of maak een AssetType binnen de juiste AssetGroup.

    Returns assettype_id. None als HaloPSA geen rechten geeft (403).
    """
    try:
        groups_resp = await client._request("GET", "/api/AssetGroup", params={"count": 100})
    except HaloPSAError as e:
        if "403" in str(e):
            return None
        raise
    groups = groups_resp if isinstance(groups_resp, list) else (
        groups_resp.get("asset_groups") or groups_resp.get("results") or []
    )
    group_id = None
    for g in groups:
        if (g.get("name") or "").strip().lower() == group_name.strip().lower():
            group_id = int(g["id"])
            break
    if group_id is None:
        # Niet aanwezig -- maken
        try:
            r = await client._request("POST", "/api/AssetGroup", json=[{"name": group_name}])
        except HaloPSAError:
            return None
        if isinstance(r, list) and r:
            group_id = int(r[0].get("id"))
        elif isinstance(r, dict) and r.get("id"):
            group_id = int(r["id"])

    if group_id is None:
        return None

    # Zoek AssetType binnen die group
    types_resp = await client._request("GET", "/api/AssetType", params={"count": 100})
    types = types_resp if isinstance(types_resp, list) else (
        types_resp.get("asset_types") or types_resp.get("results") or []
    )
    for t in types:
        if (t.get("name") or "").strip().lower() == type_name.strip().lower():
            return int(t["id"])

    # Maken aan met juiste group
    try:
        r = await client._request(
            "POST", "/api/AssetType",
            json=[{
                "name": type_name,
                "group_id": group_id,
                "assetgroup_id": group_id,
                "active": True,
            }],
        )
    except HaloPSAError:
        return None
    if isinstance(r, list) and r:
        return int(r[0].get("id"))
    if isinstance(r, dict) and r.get("id"):
        return int(r["id"])
    return None


def _asset_payload_plesk(
    sub: PleskSubscription, halopsa_client_id: int,
    site_id: int, assettype_id: int,
) -> dict[str, Any]:
    """HaloPSA Asset payload voor 1 Plesk subscription.

    Belangrijk: client_id + site_id beide nodig (HaloPSA matcht assets
    aan de klant via de site). De zichtbare naam is key_field
    (= subscription naam). inventory_number = plesk_id voor idempotent
    matching tussen poll-cycles. item_id = halopsa_product_id (= tarief
    op de recurring factuurregel).
    """
    display = sub.name or sub.main_domain or f"Plesk-{sub.plesk_id}"
    payload: dict[str, Any] = {
        "assettype_id": assettype_id,
        "client_id": halopsa_client_id,
        "site_id": site_id,
        "key_field": display[:120],
        "key_field2": sub.main_domain or "",
        "key_field3": sub.plan_name or "",
        "inventory_number": sub.plesk_id,
    }
    if sub.halopsa_product_id:
        payload["item_id"] = sub.halopsa_product_id
    return payload


def _asset_payload_openprovider(
    dom: OpenproviderDomain, halopsa_client_id: int,
    site_id: int, assettype_id: int,
) -> dict[str, Any]:
    """HaloPSA Asset payload voor 1 Openprovider domein."""
    payload: dict[str, Any] = {
        "assettype_id": assettype_id,
        "client_id": halopsa_client_id,
        "site_id": site_id,
        "key_field": dom.name[:120],
        "key_field2": dom.extension or "",
        "key_field3": "auto-renew" if dom.auto_renew else "manual",
        "inventory_number": dom.op_id,
    }
    if dom.halopsa_product_id:
        payload["item_id"] = dom.halopsa_product_id
    return payload


async def _find_existing_asset(
    client: HaloPSAClient, key: str, assettype_id: int,
) -> int | None:
    """Vind bestaande asset op key_field (= plesk_id / op_id)."""
    try:
        d = await client._request(
            "GET", "/api/Asset",
            params={"search": key, "assettype_id": assettype_id, "count": 5},
        )
    except HaloPSAError:
        return None
    items = d if isinstance(d, list) else (d.get("assets") or [])
    for a in items:
        if (a.get("key_field") or a.get("inventory_number") or "").lower() == key.lower():
            return int(a["id"])
    return None


async def sync_plesk_to_halopsa(
    db: AsyncSession, *, org_id: UUID, halopsa_client: HaloPSAClient,
    company_id: UUID | None = None,
) -> dict[str, Any]:
    """Sync alle gekoppelde Plesk subscriptions als HaloPSA Asset."""
    assettype_id = await _ensure_assettype(
        halopsa_client, PLESK_TYPE_NAME, HOSTING_GROUP_NAME,
    )
    if assettype_id is None:
        return {
            "ok": False,
            "detail": (
                "HaloPSA gaf 403 op AssetGroup/AssetType. Voeg de scope "
                "'read:assets edit:assets' toe aan onze applicatie."
            ),
            "hosts_processed": 0, "assets_upserted": 0,
            "assets_created": 0, "assets_updated": 0, "errors": [],
        }

    q = (
        select(PleskSubscription, PleskCompanyLink, Company)
        .join(PleskCompanyLink, PleskCompanyLink.subscription_id == PleskSubscription.id)
        .join(Company, Company.id == PleskCompanyLink.company_id)
    )
    if company_id is not None:
        q = q.where(PleskCompanyLink.company_id == company_id)
    triples = (await db.execute(q)).all()

    created = updated = 0
    errors: list[dict[str, Any]] = []

    for sub, _link, company in triples:
        halopsa_client_id = getattr(company, "halopsa_id", None)
        if not halopsa_client_id:
            errors.append({
                "subscription": sub.name,
                "company": company.name,
                "error": "Klant heeft geen HaloPSA koppeling (halopsa_id mist).",
            })
            continue
        site_id = await _get_main_site_id(halopsa_client, halopsa_client_id)
        if site_id is None:
            errors.append({
                "subscription": sub.name, "company": company.name,
                "error": f"Geen site gevonden voor HaloPSA client {halopsa_client_id}.",
            })
            continue
        payload = _asset_payload_plesk(sub, halopsa_client_id, site_id, assettype_id)
        try:
            if sub.halopsa_asset_id:
                payload["id"] = sub.halopsa_asset_id
                await halopsa_client._request("POST", "/api/Asset", json=[payload])
                updated += 1
            else:
                existing = await _find_existing_asset(
                    halopsa_client, sub.plesk_id, assettype_id,
                )
                if existing:
                    payload["id"] = existing
                    await halopsa_client._request("POST", "/api/Asset", json=[payload])
                    sub.halopsa_asset_id = existing
                    updated += 1
                else:
                    r = await halopsa_client._request("POST", "/api/Asset", json=[payload])
                    new_id = None
                    if isinstance(r, list) and r:
                        new_id = r[0].get("id")
                    elif isinstance(r, dict):
                        new_id = r.get("id")
                    if new_id:
                        sub.halopsa_asset_id = int(new_id)
                        created += 1
            sub.halopsa_assettype_id = assettype_id
            sub.halopsa_synced_at = datetime.now(UTC)
        except HaloPSAError as e:
            errors.append({
                "subscription": sub.name, "plesk_id": sub.plesk_id,
                "error": str(e)[:200],
            })

    await db.flush()
    return {
        "ok": True, "assettype_id": assettype_id,
        "assets_upserted": created + updated,
        "assets_created": created, "assets_updated": updated,
        "errors": errors,
    }


async def sync_openprovider_to_halopsa(
    db: AsyncSession, *, org_id: UUID, halopsa_client: HaloPSAClient,
    company_id: UUID | None = None,
) -> dict[str, Any]:
    """Sync alle gekoppelde Openprovider domeinen als HaloPSA Asset."""
    assettype_id = await _ensure_assettype(
        halopsa_client, OPENPROVIDER_TYPE_NAME, HOSTING_GROUP_NAME,
    )
    if assettype_id is None:
        return {
            "ok": False,
            "detail": "HaloPSA gaf 403. Voeg scope 'read:assets edit:assets' toe.",
            "assets_upserted": 0, "assets_created": 0, "assets_updated": 0,
            "errors": [],
        }

    q = (
        select(OpenproviderDomain, OpenproviderCompanyLink, Company)
        .join(OpenproviderCompanyLink, OpenproviderCompanyLink.domain_id == OpenproviderDomain.id)
        .join(Company, Company.id == OpenproviderCompanyLink.company_id)
    )
    if company_id is not None:
        q = q.where(OpenproviderCompanyLink.company_id == company_id)
    triples = (await db.execute(q)).all()

    created = updated = 0
    errors: list[dict[str, Any]] = []

    for dom, _link, company in triples:
        halopsa_client_id = getattr(company, "halopsa_id", None)
        if not halopsa_client_id:
            errors.append({
                "domain": dom.name, "company": company.name,
                "error": "Klant heeft geen HaloPSA koppeling.",
            })
            continue
        site_id = await _get_main_site_id(halopsa_client, halopsa_client_id)
        if site_id is None:
            errors.append({
                "domain": dom.name, "company": company.name,
                "error": f"Geen site voor HaloPSA client {halopsa_client_id}.",
            })
            continue
        payload = _asset_payload_openprovider(dom, halopsa_client_id, site_id, assettype_id)
        try:
            if dom.halopsa_asset_id:
                payload["id"] = dom.halopsa_asset_id
                await halopsa_client._request("POST", "/api/Asset", json=[payload])
                updated += 1
            else:
                existing = await _find_existing_asset(
                    halopsa_client, dom.op_id, assettype_id,
                )
                if existing:
                    payload["id"] = existing
                    await halopsa_client._request("POST", "/api/Asset", json=[payload])
                    dom.halopsa_asset_id = existing
                    updated += 1
                else:
                    r = await halopsa_client._request("POST", "/api/Asset", json=[payload])
                    new_id = None
                    if isinstance(r, list) and r:
                        new_id = r[0].get("id")
                    elif isinstance(r, dict):
                        new_id = r.get("id")
                    if new_id:
                        dom.halopsa_asset_id = int(new_id)
                        created += 1
            dom.halopsa_assettype_id = assettype_id
            dom.halopsa_synced_at = datetime.now(UTC)
        except HaloPSAError as e:
            errors.append({
                "domain": dom.name, "op_id": dom.op_id,
                "error": str(e)[:200],
            })

    await db.flush()
    return {
        "ok": True, "assettype_id": assettype_id,
        "assets_upserted": created + updated,
        "assets_created": created, "assets_updated": updated,
        "errors": errors,
    }
