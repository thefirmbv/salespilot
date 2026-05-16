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
from salespilot.models.integrations import Integration


router = APIRouter(prefix="/snelstart", tags=["snelstart"])


SNELSTART_KIND = "snelstart"


# ----------------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------------


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
