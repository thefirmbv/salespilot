"""SnelStart 12 API endpoints.

Routes
------
GET  /snelstart/administraties               -- list administrations for picker
POST /snelstart/administraties/select        -- set the active admin
POST /snelstart/sepa-fix/preview             -- dry-run SEPA bulk fix
POST /snelstart/sepa-fix/apply               -- commit SEPA bulk fix
GET  /snelstart/dashboard                    -- monthly aggregation per group

The /test, /config, /sync endpoints stay on /integrations/snelstart so
they share the standard integration UX with HaloPSA etc.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from salespilot.deps import CurrentAuth, Db
from salespilot.integrations.snelstart import (
    SnelStartClient, SnelStartCredentials, SnelStartError,
)
from salespilot.integrations.snelstart_sync import (
    aggregate_monthly_by_group, sepa_bulk_fix_for_org,
)
from salespilot.integrations.snelstart_sepa_sync import (
    sync_doorlopende_machtigingen,
)
from salespilot.models.integrations import Integration


router = APIRouter(prefix="/snelstart", tags=["snelstart"])


SNELSTART_KIND = "snelstart"


# ----------------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------------


def _has_creds(row: Integration) -> bool:
    cfg = row.config_json or {}
    return all([
        cfg.get("subscription_key"),
        cfg.get("client_id"),
        cfg.get("client_secret"),
    ])


async def _get_snelstart_row(db) -> Integration:
    row = (
        await db.execute(
            select(Integration).where(Integration.kind == SNELSTART_KIND)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=400, detail="SnelStart is nog niet ingesteld.")
    return row


def _creds_from_row(row: Integration) -> SnelStartCredentials:
    cfg = row.config_json or {}
    return SnelStartCredentials(
        subscription_key=cfg.get("subscription_key", ""),
        client_id=cfg.get("client_id", ""),
        client_secret=cfg.get("client_secret", ""),
        administratie_id=cfg.get("administratie_id"),
        base_url=cfg.get("base_url") or "https://b2bapi.snelstart.nl",
    )


# ----------------------------------------------------------------------
# Administraties (picker for first-time setup)
# ----------------------------------------------------------------------


class AdministratieRow(BaseModel):
    id: str
    naam: str
    actief: bool = True


@router.get("/administraties", response_model=list[AdministratieRow])
async def list_administraties(auth: CurrentAuth, db: Db) -> list[AdministratieRow]:
    row = await _get_snelstart_row(db)
    try:
        async with SnelStartClient(_creds_from_row(row)) as c:
            data = await c.list_administraties()
    except SnelStartError as e:
        raise HTTPException(status_code=502, detail=str(e))
    out: list[AdministratieRow] = []
    for a in data:
        out.append(AdministratieRow(
            id=str(a.get("id", "")),
            naam=a.get("naam") or a.get("name") or "(zonder naam)",
            actief=bool(a.get("actief", True)),
        ))
    return out


class SelectAdminBody(BaseModel):
    administratie_id: str
    administratie_naam: str | None = None


@router.post("/administraties/select")
async def select_administratie(
    body: SelectAdminBody, auth: CurrentAuth, db: Db,
) -> dict[str, Any]:
    row = await _get_snelstart_row(db)
    cfg = dict(row.config_json or {})
    cfg["administratie_id"] = body.administratie_id
    if body.administratie_naam:
        cfg["administratie_naam"] = body.administratie_naam
    row.config_json = cfg
    await db.commit()
    return {"ok": True, "administratie_id": body.administratie_id}


# ----------------------------------------------------------------------
# SEPA bulk fix
# ----------------------------------------------------------------------


class SepaFixRequest(BaseModel):
    from_date: datetime | None = None
    to_date: datetime | None = None
    # Defaults: last 90 days if nothing supplied
    days_back: int | None = 90


class SepaFixRow(BaseModel):
    factuur_id: str | None = None
    factuurnummer: str | None = None
    factuurdatum: str | None = None
    relatie_id: str | None = None
    relatie_naam: str = ""
    bedrag: float = 0.0
    action: str  # would_fix | fixing | fixed | error


class SepaFixResult(BaseModel):
    ok: bool
    dry_run: bool
    scanned: int
    missing_flag: int
    fixable: int
    fixed: int
    rows: list[SepaFixRow]
    errors: list[dict[str, Any]]


def _resolve_window(req: SepaFixRequest) -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    to = req.to_date or now
    if req.from_date:
        return req.from_date, to
    days = req.days_back or 90
    return to - timedelta(days=days), to


@router.post("/sepa-fix/preview", response_model=SepaFixResult)
async def sepa_fix_preview(
    body: SepaFixRequest, auth: CurrentAuth, db: Db,
) -> SepaFixResult:
    """Show which invoices WOULD be flipped to isIncasso=true. No
    SnelStart writes happen during preview."""
    row = await _get_snelstart_row(db)
    frm, to = _resolve_window(body)
    try:
        async with SnelStartClient(_creds_from_row(row)) as c:
            res = await sepa_bulk_fix_for_org(
                c, dry_run=True, from_date=frm, to_date=to,
            )
    except SnelStartError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return SepaFixResult(**res)


@router.post("/sepa-fix/apply", response_model=SepaFixResult)
async def sepa_fix_apply(
    body: SepaFixRequest, auth: CurrentAuth, db: Db,
) -> SepaFixResult:
    """Commit the SEPA flag for invoices that have an active mandate but
    don't carry isIncasso=true yet."""
    row = await _get_snelstart_row(db)
    frm, to = _resolve_window(body)
    try:
        async with SnelStartClient(_creds_from_row(row)) as c:
            res = await sepa_bulk_fix_for_org(
                c, dry_run=False, from_date=frm, to_date=to,
            )
    except SnelStartError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return SepaFixResult(**res)


# ----------------------------------------------------------------------
# Financieel > Dashboard (monthly revenue per group)
# ----------------------------------------------------------------------


class DashboardGroup(BaseModel):
    id: str
    naam: str


class DashboardResponse(BaseModel):
    months: list[str]
    groups: list[DashboardGroup]
    matrix: dict[str, dict[str, float]]
    totals_per_month: dict[str, float]
    totals_per_group: dict[str, float]
    grand_total: float
    invoice_count: int
    from_date: str
    to_date: str


@router.get("/dashboard", response_model=DashboardResponse)
async def financieel_dashboard(
    auth: CurrentAuth, db: Db,
    months: int = Query(default=4, ge=1, le=24),
) -> DashboardResponse:
    """Monthly revenue per group for the last N months. Powers the
    Financieel > Dashboard view."""
    row = await _get_snelstart_row(db)
    try:
        async with SnelStartClient(_creds_from_row(row)) as c:
            data = await aggregate_monthly_by_group(c, months=months)
    except SnelStartError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return DashboardResponse(**data)


# ----------------------------------------------------------------------
# Connection test (configurabel zonder gelijk te schrijven)
# ----------------------------------------------------------------------


class ConnectionTestResult(BaseModel):
    configured: bool
    ok: bool
    administraties_count: int = 0
    administraties: list[dict[str, Any]] = []
    error: str | None = None


@router.get("/connection-test", response_model=ConnectionTestResult)
async def connection_test(auth: CurrentAuth, db: Db) -> ConnectionTestResult:
    """Test of credentials werken. Geen mutations."""
    row = (
        await db.execute(
            select(Integration).where(Integration.kind == SNELSTART_KIND)
        )
    ).scalar_one_or_none()
    if row is None:
        return ConnectionTestResult(configured=False, ok=False,
                                    error="SnelStart integratie nog niet aangemaakt")
    if not _has_creds(row):
        return ConnectionTestResult(configured=False, ok=False,
                                    error="Credentials ontbreken (subscription_key + client_id + client_secret)")
    try:
        async with SnelStartClient(_creds_from_row(row)) as c:
            data = await c.test_connection()
        return ConnectionTestResult(
            configured=True, ok=True,
            administraties_count=data.get("administraties_count", 0),
            administraties=data.get("administraties", []),
        )
    except SnelStartError as e:
        return ConnectionTestResult(configured=True, ok=False, error=str(e)[:300])


# ----------------------------------------------------------------------
# Settings -- credentials invoeren / wissen
# ----------------------------------------------------------------------


class SnelstartConfigStatus(BaseModel):
    exists: bool
    enabled: bool
    has_subscription_key: bool = False
    has_client_id: bool = False
    has_client_secret: bool = False
    administratie_id: str | None = None
    administratie_naam: str | None = None
    base_url: str | None = None


class SnelstartConfigBody(BaseModel):
    subscription_key: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    administratie_id: str | None = None
    administratie_naam: str | None = None
    base_url: str | None = None
    enabled: bool | None = None


@router.get("/config", response_model=SnelstartConfigStatus)
async def get_config(auth: CurrentAuth, db: Db) -> SnelstartConfigStatus:
    row = (
        await db.execute(
            select(Integration).where(Integration.kind == SNELSTART_KIND)
        )
    ).scalar_one_or_none()
    if row is None:
        return SnelstartConfigStatus(exists=False, enabled=False)
    cfg = row.config_json or {}
    return SnelstartConfigStatus(
        exists=True,
        enabled=bool(row.is_enabled),
        has_subscription_key=bool(cfg.get("subscription_key")),
        has_client_id=bool(cfg.get("client_id")),
        has_client_secret=bool(cfg.get("client_secret")),
        administratie_id=cfg.get("administratie_id"),
        administratie_naam=cfg.get("administratie_naam"),
        base_url=cfg.get("base_url"),
    )


@router.put("/config")
async def set_config(
    body: SnelstartConfigBody, auth: CurrentAuth, db: Db,
) -> dict[str, Any]:
    """Schrijf credentials. Lege velden in body worden NIET gewist
    (voor partial updates) tenzij je expliciet \"\" stuurt."""
    row = (
        await db.execute(
            select(Integration).where(Integration.kind == SNELSTART_KIND)
        )
    ).scalar_one_or_none()
    if row is None:
        from uuid import uuid4
        row = Integration(
            id=uuid4(),
            org_id=auth.org_id,
            kind=SNELSTART_KIND,
            is_enabled=False,
            config_json={},
        )
        db.add(row)
        await db.flush()

    cfg = dict(row.config_json or {})
    for key in ("subscription_key", "client_id", "client_secret",
                "administratie_id", "administratie_naam", "base_url"):
        val = getattr(body, key, None)
        if val is not None:
            cfg[key] = val.strip() if isinstance(val, str) else val
    row.config_json = cfg
    if body.enabled is not None:
        row.is_enabled = body.enabled
    await db.flush()
    return {"ok": True}


@router.delete("/config/credentials")
async def clear_credentials(auth: CurrentAuth, db: Db) -> dict[str, Any]:
    """Wis credentials maar laat config (administratie etc) staan."""
    row = (
        await db.execute(
            select(Integration).where(Integration.kind == SNELSTART_KIND)
        )
    ).scalar_one_or_none()
    if row is None:
        return {"ok": True}
    cfg = dict(row.config_json or {})
    for key in ("subscription_key", "client_id", "client_secret"):
        cfg.pop(key, None)
    row.config_json = cfg
    row.is_enabled = False
    await db.flush()
    return {"ok": True}


# ----------------------------------------------------------------------
# SEPA machtiging sync (doorlopendeIncassoMachtiging op verkoopboekingen)
# ----------------------------------------------------------------------


class SepaMachtigingSyncResult(BaseModel):
    ok: bool
    dry_run: bool
    error: str | None = None
    mandates_total: int = 0
    matched_in_snelstart: int = 0
    mandates_no_match: int = 0
    machtigingen_existing: int = 0
    machtigingen_created: int = 0
    boekingen_scanned: int = 0
    boekingen_patched: int = 0
    boekingen_already_set: int = 0
    errors: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []


@router.post("/sepa-machtiging-sync/preview",
             response_model=SepaMachtigingSyncResult)
async def sepa_machtiging_sync_preview(
    auth: CurrentAuth, db: Db,
    days_back: int = Query(default=90, ge=1, le=365),
) -> SepaMachtigingSyncResult:
    """Dry-run: laat zien wat er gepatched zou worden."""
    row = (
        await db.execute(
            select(Integration).where(Integration.kind == SNELSTART_KIND)
        )
    ).scalar_one_or_none()
    if row is None or not _has_creds(row):
        return SepaMachtigingSyncResult(
            ok=False, dry_run=True,
            error="Credentials ontbreken. Vul in bij Settings > Snelstart.",
        )
    try:
        async with SnelStartClient(_creds_from_row(row)) as c:
            res = await sync_doorlopende_machtigingen(
                db, c, auth.org_id, dry_run=True, days_back=days_back,
            )
    except SnelStartError as e:
        return SepaMachtigingSyncResult(
            ok=False, dry_run=True, error=str(e)[:300],
        )
    return SepaMachtigingSyncResult(**res)


@router.post("/sepa-machtiging-sync/apply",
             response_model=SepaMachtigingSyncResult)
async def sepa_machtiging_sync_apply(
    auth: CurrentAuth, db: Db,
    days_back: int = Query(default=90, ge=1, le=365),
) -> SepaMachtigingSyncResult:
    """Echt pushen: zet doorlopendeIncassoMachtiging op verkoopboekingen."""
    row = (
        await db.execute(
            select(Integration).where(Integration.kind == SNELSTART_KIND)
        )
    ).scalar_one_or_none()
    if row is None or not _has_creds(row):
        return SepaMachtigingSyncResult(
            ok=False, dry_run=False,
            error="Credentials ontbreken. Vul in bij Settings > Snelstart.",
        )
    try:
        async with SnelStartClient(_creds_from_row(row)) as c:
            res = await sync_doorlopende_machtigingen(
                db, c, auth.org_id, dry_run=False, days_back=days_back,
            )
    except SnelStartError as e:
        return SepaMachtigingSyncResult(
            ok=False, dry_run=False, error=str(e)[:300],
        )
    return SepaMachtigingSyncResult(**res)
