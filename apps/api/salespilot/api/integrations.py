"""HaloPSA integration endpoints.

  GET  /integrations/halopsa                  read config (secret masked)
  PUT  /integrations/halopsa                  create or update config
  POST /integrations/halopsa/test             test the connection
  POST /integrations/halopsa/sync             pull clients into companies
  POST /companies/{company_id}/push-to-halopsa
  GET  /companies/{company_id}/halopsa-quotations
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from salespilot.deps import CurrentAuth, Db
from salespilot.integrations.halopsa import (
    HaloPSAClient,
    HaloPSACredentials,
    HaloPSAError,
)
from salespilot.models.crm import Company, CompanySource
from salespilot.models.integrations import Integration
from salespilot.schemas.integrations import (
    HaloPSAConfig,
    IntegrationPublic,
    IntegrationUpsert,
    SyncResult,
    TestConnectionResult,
)

router = APIRouter(prefix="/integrations", tags=["integrations"])

HALOPSA_KIND = "halopsa"

# Keys that are safe to echo back in the public view.
_PUBLIC_CONFIG_KEYS = ("base_url", "client_id", "tenant", "scopes")


def _public_config(cfg: dict[str, Any]) -> dict[str, Any]:
    out = {k: cfg.get(k) for k in _PUBLIC_CONFIG_KEYS}
    # Mask client_secret presence
    out["client_secret_set"] = bool(cfg.get("client_secret"))
    return out


def _to_public(row: Integration) -> IntegrationPublic:
    return IntegrationPublic(
        id=row.id,
        kind=row.kind,
        is_enabled=row.is_enabled,
        config_public=_public_config(row.config_json or {}),
        last_sync_at=row.last_sync_at,
        last_sync_status=row.last_sync_status,
        last_sync_message=row.last_sync_message,
        updated_at=row.updated_at,
    )


async def _get_halopsa_integration(db, auth_org_id: UUID) -> Integration | None:
    res = await db.execute(
        select(Integration).where(Integration.kind == HALOPSA_KIND)
    )
    return res.scalar_one_or_none()


def _creds_from(integration: Integration) -> HaloPSACredentials:
    cfg = integration.config_json or {}
    return HaloPSACredentials(
        base_url=cfg.get("base_url", ""),
        client_id=cfg.get("client_id", ""),
        client_secret=cfg.get("client_secret", ""),
        tenant=cfg.get("tenant"),
        scopes=cfg.get("scopes") or "all",
    )


# ---- config: read / upsert ----


@router.get("/halopsa", response_model=IntegrationPublic | None)
async def get_halopsa(auth: CurrentAuth, db: Db) -> IntegrationPublic | None:
    row = await _get_halopsa_integration(db, auth.org_id)
    if row is None:
        return None
    return _to_public(row)


@router.put("/halopsa", response_model=IntegrationPublic)
async def upsert_halopsa(
    data: IntegrationUpsert, auth: CurrentAuth, db: Db
) -> IntegrationPublic:
    row = await _get_halopsa_integration(db, auth.org_id)
    cfg_dict = data.config.model_dump()
    if row is None:
        row = Integration(
            id=uuid4(),
            org_id=auth.org_id,
            kind=HALOPSA_KIND,
            is_enabled=data.is_enabled,
            config_json=cfg_dict,
        )
        db.add(row)
    else:
        row.is_enabled = data.is_enabled
        # Don't overwrite client_secret with the empty string the UI sends
        # when it didn't ask the user for it.
        if not cfg_dict.get("client_secret"):
            cfg_dict["client_secret"] = (row.config_json or {}).get(
                "client_secret", ""
            )
        row.config_json = cfg_dict
    await db.flush()
    await db.refresh(row)
    return _to_public(row)


# ---- test connection ----


@router.post("/halopsa/test", response_model=TestConnectionResult)
async def test_halopsa(auth: CurrentAuth, db: Db) -> TestConnectionResult:
    row = await _get_halopsa_integration(db, auth.org_id)
    if row is None:
        raise HTTPException(status_code=400, detail="HaloPSA not configured yet")
    creds = _creds_from(row)
    try:
        async with HaloPSAClient(creds) as client:
            await client.test_connection()
        return TestConnectionResult(
            ok=True, detail="Authenticated successfully.", token_present=True
        )
    except HaloPSAError as e:
        return TestConnectionResult(ok=False, detail=str(e))


# ---- sync clients -> companies ----


def _map_client(c: dict[str, Any]) -> dict[str, Any]:
    """Translate a HaloPSA Client into Company column values."""
    return {
        "name": c.get("name") or "Unnamed",
        "domain": c.get("website") or c.get("inactive_website") or None,
        "industry": (c.get("sector_name") or c.get("sector") or None),
        "description": c.get("notes") or None,
    }


@router.post("/halopsa/sync", response_model=SyncResult)
async def sync_halopsa(auth: CurrentAuth, db: Db) -> SyncResult:
    row = await _get_halopsa_integration(db, auth.org_id)
    if row is None or not row.is_enabled:
        raise HTTPException(
            status_code=400, detail="HaloPSA not configured or disabled"
        )
    creds = _creds_from(row)

    try:
        async with HaloPSAClient(creds) as client:
            clients = await client.list_clients()
    except HaloPSAError as e:
        row.last_sync_at = datetime.now(UTC)
        row.last_sync_status = "error"
        row.last_sync_message = str(e)[:1000]
        await db.flush()
        return SyncResult(ok=False, detail=str(e))

    # Index existing companies by halopsa_id for fast lookup.
    existing_rows = (
        await db.execute(
            select(Company).where(Company.halopsa_id.is_not(None))
        )
    ).scalars().all()
    by_halopsa_id: dict[int, Company] = {
        c.halopsa_id: c for c in existing_rows if c.halopsa_id is not None
    }

    created = 0
    updated = 0
    now = datetime.now(UTC)
    for raw in clients:
        try:
            halopsa_id = int(raw.get("id"))
        except (TypeError, ValueError):
            continue
        mapped = _map_client(raw)
        existing = by_halopsa_id.get(halopsa_id)
        if existing:
            for k, v in mapped.items():
                setattr(existing, k, v)
            existing.source = CompanySource.HALOPSA
            existing.halopsa_synced_at = now
            updated += 1
        else:
            db.add(
                Company(
                    id=uuid4(),
                    org_id=auth.org_id,
                    name=mapped["name"],
                    domain=mapped["domain"],
                    industry=mapped["industry"],
                    description=mapped["description"],
                    source=CompanySource.HALOPSA,
                    halopsa_id=halopsa_id,
                    halopsa_synced_at=now,
                )
            )
            created += 1

    row.last_sync_at = now
    row.last_sync_status = "ok"
    row.last_sync_message = f"Fetched {len(clients)} clients"
    await db.flush()

    return SyncResult(
        ok=True,
        detail=f"Synced {len(clients)} clients ({created} new, {updated} updated)",
        fetched=len(clients),
        created=created,
        updated=updated,
    )


# ---- push a single company to HaloPSA ----


# A second router for company-scoped endpoints; mounted on /companies in main.
companies_extra_router = APIRouter(prefix="/companies", tags=["companies"])


@companies_extra_router.post(
    "/{company_id}/push-to-halopsa", response_model=dict[str, Any]
)
async def push_to_halopsa(
    company_id: UUID, auth: CurrentAuth, db: Db
) -> dict[str, Any]:
    integ = await _get_halopsa_integration(db, auth.org_id)
    if integ is None or not integ.is_enabled:
        raise HTTPException(
            status_code=400, detail="HaloPSA not configured or disabled"
        )
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="company not found")
    if company.halopsa_id is not None:
        raise HTTPException(
            status_code=409,
            detail=f"already linked to HaloPSA client {company.halopsa_id}",
        )

    # Minimum payload HaloPSA accepts. Site is required for quotes/tickets;
    # 'main_site_name' = 'HaloPSA' per the user's request.
    payload: dict[str, Any] = {
        "name": company.name,
        "inactive": False,
        "main_site_name": "HaloPSA",
    }
    if company.domain:
        payload["website"] = company.domain
    if company.description:
        payload["notes"] = company.description

    creds = _creds_from(integ)
    try:
        async with HaloPSAClient(creds) as client:
            result = await client.create_client(payload)
    except HaloPSAError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    new_id = result.get("id")
    if not isinstance(new_id, int):
        raise HTTPException(
            status_code=502, detail=f"HaloPSA did not return a client id: {result!r}"
        )

    company.halopsa_id = new_id
    company.source = CompanySource.HALOPSA_PUSHED
    company.halopsa_synced_at = datetime.now(UTC)
    await db.flush()

    return {"halopsa_id": new_id, "source": company.source.value}


@companies_extra_router.get("/{company_id}/halopsa-quotations")
async def list_halopsa_quotations(
    company_id: UUID, auth: CurrentAuth, db: Db
) -> list[dict[str, Any]]:
    integ = await _get_halopsa_integration(db, auth.org_id)
    if integ is None or not integ.is_enabled:
        return []
    company = await db.get(Company, company_id)
    if company is None or company.halopsa_id is None:
        return []
    creds = _creds_from(integ)
    try:
        async with HaloPSAClient(creds) as client:
            return await client.list_quotations_for_client(company.halopsa_id)
    except HaloPSAError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
