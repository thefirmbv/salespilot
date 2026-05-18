"""NMBRS integration API: OAuth flow + sync endpoints.

Routes:
  GET  /integrations/nmbrs/oauth/start    -> redirect naar NMBRS consent
  GET  /integrations/nmbrs/oauth/callback -> verwerkt code, slaat tokens op
  GET  /integrations/nmbrs/status         -> connect-status voor UI
  POST /integrations/nmbrs/sync-employees -> sync medewerkers naar employees-tabel
  POST /integrations/nmbrs/sync-absences  -> sync verlof naar HaloPSA Appointment
"""

from __future__ import annotations

from datetime import datetime, UTC
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select

from salespilot.deps import CurrentAuth, Db, DbNoTenant
from salespilot.models.integrations import Integration
from salespilot.models.inventory import Employee
from salespilot.integrations.nmbrs import (
    NmbrsClient, NmbrsAuthError, NmbrsConfigError,
    build_authorize_url, exchange_code_for_tokens, store_tokens,
)


router = APIRouter(prefix="/integrations/nmbrs", tags=["nmbrs"])


# ----- Status / OAuth flow -------------------------------------------


class NmbrsStatus(BaseModel):
    configured: bool
    connected: bool
    status: str  # 'ready_for_consent' / 'connected' / 'expired' / ...
    granted_scopes: list[str]
    access_token_expires_at: str | None
    last_token_refresh_at: str | None
    last_sync_at: str | None


@router.get("/status", response_model=NmbrsStatus)
async def nmbrs_status(auth: CurrentAuth, db: Db) -> NmbrsStatus:
    """Check of NMBRS gekoppeld + bruikbaar is."""
    integ = (
        await db.execute(select(Integration).where(Integration.kind == "nmbrs"))
    ).scalar_one_or_none()
    if not integ:
        return NmbrsStatus(
            configured=False, connected=False, status="not_configured",
            granted_scopes=[], access_token_expires_at=None,
            last_token_refresh_at=None, last_sync_at=None,
        )
    cfg = integ.config_json or {}
    has_credentials = all(cfg.get(k) for k in
                          ("client_id", "client_secret", "subscription_key"))
    has_tokens = bool(cfg.get("access_token") and cfg.get("refresh_token"))
    return NmbrsStatus(
        configured=has_credentials,
        connected=has_tokens,
        status=cfg.get("status", "unknown"),
        granted_scopes=cfg.get("granted_scopes", []),
        access_token_expires_at=cfg.get("access_token_expires_at"),
        last_token_refresh_at=cfg.get("last_token_refresh_at"),
        last_sync_at=(
            integ.last_sync_at.isoformat() if integ.last_sync_at else None
        ),
    )


class OAuthStartResponse(BaseModel):
    authorize_url: str


@router.get("/oauth/start", response_model=OAuthStartResponse)
async def oauth_start(auth: CurrentAuth, db: Db) -> OAuthStartResponse:
    """Returnt de NMBRS consent-URL. Frontend doet zelf window.location.

    Reden voor JSON i.p.v. directe redirect: <a href> in browser stuurt
    geen Authorization-header mee, dus de redirect-route geeft
    'missing authorization'. Frontend pakt URL via fetch (met token)
    en zet daarna window.location.
    """
    integ = (
        await db.execute(select(Integration).where(Integration.kind == "nmbrs"))
    ).scalar_one_or_none()
    if not integ:
        raise HTTPException(status_code=400, detail="NMBRS not configured")
    try:
        url = build_authorize_url(integ, state=str(auth.org_id))
    except NmbrsConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return OAuthStartResponse(authorize_url=url)


@router.get("/oauth/callback")
async def oauth_callback(
    db: DbNoTenant,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> RedirectResponse:
    """Callback van NMBRS na consent. Geen auth-dependency: dit is
    de redirect-target van NMBRS' identity service.
    """
    # Frontend-redirect helper
    def back(ok: bool, msg: str) -> RedirectResponse:
        q = f"?nmbrs={'ok' if ok else 'error'}&msg={msg}"
        return RedirectResponse(f"/settings/integrations/nmbrs{q}", status_code=302)

    if error:
        return back(False, error_description or error)
    if not code or not state:
        return back(False, "missing_code_or_state")

    try:
        org_id = UUID(state)
    except (ValueError, TypeError):
        return back(False, "bad_state")

    # No-tenant route: NMBRS callbackt zonder onze JWT. App draait als
    # salespilot_app (NOBYPASSRLS) dus zonder app.current_org_id GUC
    # geeft RLS 0 rijen. We zetten de context expliciet uit state.
    from sqlalchemy import text
    await db.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))

    integ = (
        await db.execute(
            select(Integration)
            .where(Integration.kind == "nmbrs", Integration.org_id == org_id)
        )
    ).scalar_one_or_none()
    if not integ:
        return back(False, "integration_not_found")

    try:
        token_response = await exchange_code_for_tokens(integ, code)
        store_tokens(integ, token_response)
        integ.is_enabled = True
        await db.commit()
    except (NmbrsConfigError, NmbrsAuthError) as e:
        return back(False, str(e)[:120])

    return back(True, "connected")


# ----- Sync endpoints (medewerkers + verlof) -------------------------


class SyncResult(BaseModel):
    ok: bool
    employees_created: int = 0
    employees_updated: int = 0
    employees_unchanged: int = 0
    companies_seen: int = 0
    skipped_no_email: int = 0
    error: str | None = None


@router.post("/sync-employees", response_model=SyncResult)
async def sync_employees(auth: CurrentAuth, db: Db) -> SyncResult:
    """Haal medewerkers op uit NMBRS, upsert naar employees-tabel.

    Match-key: nmbrs_employee_id. Bij eerste import worden ze als
    'active' aangemaakt. Updates raken alleen full_name + email +
    nmbrs_company_id, NIET zelf-ingevulde velden zoals notes/role.
    """
    integ = (
        await db.execute(select(Integration).where(Integration.kind == "nmbrs"))
    ).scalar_one_or_none()
    if not integ:
        raise HTTPException(status_code=400, detail="NMBRS not configured")

    client = NmbrsClient(integ, db)
    try:
        companies = await client.companies()
    except NmbrsAuthError as e:
        return SyncResult(ok=False, error=str(e)[:160])
    except NmbrsConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))

    created = updated = unchanged = skipped = 0

    for company in companies:
        company_id = company.get("companyId") or company.get("id")
        if not company_id:
            continue
        company_id = str(company_id)

        try:
            employees_raw = await client.employees(company_id)
        except Exception:
            continue

        for emp in employees_raw:
            nmbrs_emp_id = emp.get("employeeId") or emp.get("id")
            if not nmbrs_emp_id:
                continue
            nmbrs_emp_id = str(nmbrs_emp_id)

            # NMBRS basic info via employee-list (employeeBasicInfo) of detail
            basic = emp.get("employeeBasicInfo") or {}
            first = (basic.get("firstName") or "").strip()
            last = (basic.get("lastName") or "").strip()
            prefix = (basic.get("prefix") or "").strip()

            # Voor email moeten we de detail-call doen
            email = None
            role = None
            detail = await client.employee_detail(nmbrs_emp_id)
            if detail:
                pi = detail.get("personalInfo") or {}
                contact = pi.get("contactInfo") or {}
                email = (contact.get("businessEmail") or contact.get("privateEmail") or "").strip().lower() or None
                # Naam ook uit detail (heeft betrouwbaardere data)
                bi = pi.get("basicInfo") or {}
                first = (bi.get("firstName") or first or "").strip()
                last = (bi.get("lastName") or last or "").strip()
                prefix = (bi.get("prefix") or prefix or "").strip()
                # Functie ook ophalen
                fn = detail.get("function") or {}
                if isinstance(fn, dict):
                    role = (fn.get("description") or fn.get("name") or "").strip() or None

            full = " ".join(p for p in [first, prefix, last] if p)
            if not full:
                skipped += 1
                continue

            # Upsert by nmbrs_employee_id
            existing = (
                await db.execute(
                    select(Employee)
                    .where(Employee.nmbrs_employee_id == nmbrs_emp_id)
                )
            ).scalar_one_or_none()

            now = datetime.now(UTC)
            if existing:
                changed = False
                if existing.full_name != full:
                    existing.full_name = full; changed = True
                if email and existing.email != email:
                    existing.email = email; changed = True
                if existing.nmbrs_company_id != company_id:
                    existing.nmbrs_company_id = company_id; changed = True
                # role alleen overschrijven als nog leeg (eindgebruiker
                # blijft eigenaar als die het zelf heeft ingevuld)
                if role and not existing.role:
                    existing.role = role; changed = True
                if changed:
                    existing.updated_at = now
                    updated += 1
                else:
                    unchanged += 1
            else:
                db.add(Employee(
                    id=uuid4(), org_id=auth.org_id,
                    full_name=full, email=email, role=role,
                    status="active",
                    nmbrs_employee_id=nmbrs_emp_id,
                    nmbrs_company_id=company_id,
                    created_at=now, updated_at=now,
                ))
                created += 1

    integ.last_sync_at = datetime.now(UTC)
    integ.last_sync_status = "ok"
    integ.last_sync_message = (
        f"sync OK: {created} new, {updated} updated, "
        f"{unchanged} unchanged, {skipped} skipped"
    )
    await db.flush()

    return SyncResult(
        ok=True,
        employees_created=created, employees_updated=updated,
        employees_unchanged=unchanged, companies_seen=len(companies),
        skipped_no_email=skipped,
    )


@router.post("/sync-absences", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def sync_absences(auth: CurrentAuth, db: Db) -> dict:
    """Placeholder: synct NMBRS verlof -> HaloPSA Appointment.

    Implementatie volgt nadat de OAuth-flow eenmaal getest is en we
    weten welke velden exact in /api/employees/{id}/absences zitten
    in productie (verschilt soms van docs). Eerst sync-employees
    werkend krijgen, dan absences.
    """
    raise HTTPException(
        status_code=501,
        detail="Absence sync wordt geactiveerd na succesvolle eerste OAuth-flow + employee-sync",
    )
