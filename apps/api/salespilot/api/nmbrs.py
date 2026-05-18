"""NMBRS integration API: OAuth flow + sync endpoints (multi-debtor)."""

from __future__ import annotations

from datetime import datetime, UTC
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select, text

from salespilot.deps import CurrentAuth, Db, DbNoTenant
from salespilot.models.integrations import Integration
from salespilot.models.inventory import Employee
from salespilot.integrations.nmbrs import (
    NmbrsClient, NmbrsAuthError, NmbrsConfigError,
    build_authorize_url, exchange_code_for_tokens,
    store_debtor_tokens, get_debtors, fetch_debtor_for_token,
)


router = APIRouter(prefix="/integrations/nmbrs", tags=["nmbrs"])


# ----- Status --------------------------------------------------------


class DebtorStatus(BaseModel):
    debtor_id: str
    name: str
    granted_scopes: list[str]
    access_token_expires_at: str | None
    last_token_refresh_at: str | None


class NmbrsStatus(BaseModel):
    configured: bool
    connected: bool
    debtors: list[DebtorStatus]
    last_sync_at: str | None


@router.get("/status", response_model=NmbrsStatus)
async def nmbrs_status(auth: CurrentAuth, db: Db) -> NmbrsStatus:
    integ = (
        await db.execute(select(Integration).where(Integration.kind == "nmbrs"))
    ).scalar_one_or_none()
    if not integ:
        return NmbrsStatus(
            configured=False, connected=False, debtors=[], last_sync_at=None,
        )
    cfg = integ.config_json or {}
    has_credentials = all(cfg.get(k) for k in
                          ("client_id", "client_secret", "subscription_key"))
    debtors_raw = get_debtors(integ)
    debtors = [
        DebtorStatus(
            debtor_id=did,
            name=d.get("name", "Unknown"),
            granted_scopes=d.get("granted_scopes", []),
            access_token_expires_at=d.get("access_token_expires_at"),
            last_token_refresh_at=d.get("last_token_refresh_at"),
        )
        for did, d in debtors_raw.items()
        if did != "__legacy__"  # verbergen voor UI
    ]
    return NmbrsStatus(
        configured=has_credentials,
        connected=len(debtors) > 0,
        debtors=debtors,
        last_sync_at=(
            integ.last_sync_at.isoformat() if integ.last_sync_at else None
        ),
    )


# ----- OAuth flow ----------------------------------------------------


class OAuthStartResponse(BaseModel):
    authorize_url: str


@router.get("/oauth/start", response_model=OAuthStartResponse)
async def oauth_start(auth: CurrentAuth, db: Db) -> OAuthStartResponse:
    """Returnt de NMBRS consent-URL. Frontend doet zelf window.location."""
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

    # RLS-context expliciet zetten (DbNoTenant + salespilot_app heeft NOBYPASSRLS)
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
    except (NmbrsConfigError, NmbrsAuthError) as e:
        return back(False, f"token_exchange_failed: {str(e)[:120]}")

    # Detecteer welke debtor deze token bij hoort
    cfg = integ.config_json or {}
    debtor_info = await fetch_debtor_for_token(
        token_response["access_token"], cfg.get("subscription_key", ""),
    )
    if not debtor_info:
        return back(False, "debtor_detect_failed")

    debtor_id, debtor_name = debtor_info
    store_debtor_tokens(integ, debtor_id, debtor_name, token_response)
    integ.is_enabled = True
    await db.commit()

    return back(True, f"connected_{debtor_name}")


@router.delete("/debtors/{debtor_id}")
async def disconnect_debtor(
    auth: CurrentAuth, db: Db, debtor_id: str,
) -> dict:
    """Verwijder tokens van één debtor."""
    integ = (
        await db.execute(select(Integration).where(Integration.kind == "nmbrs"))
    ).scalar_one_or_none()
    if not integ:
        raise HTTPException(status_code=404, detail="not configured")
    cfg = dict(integ.config_json or {})
    debtors = dict(cfg.get("debtors") or {})
    if debtor_id not in debtors:
        raise HTTPException(status_code=404, detail="debtor not connected")
    removed = debtors.pop(debtor_id)
    cfg["debtors"] = debtors
    if not debtors:
        integ.is_enabled = False
        cfg["status"] = "no_debtors"
    integ.config_json = cfg
    await db.flush()
    return {"ok": True, "removed": removed.get("name")}


# ----- Sync endpoint -------------------------------------------------


class DebtorSyncResult(BaseModel):
    debtor_id: str
    debtor_name: str
    ok: bool
    employees_created: int = 0
    employees_updated: int = 0
    employees_unchanged: int = 0
    companies_seen: int = 0
    skipped_no_name: int = 0
    error: str | None = None


class SyncResult(BaseModel):
    ok: bool
    debtors_synced: int = 0
    total_created: int = 0
    total_updated: int = 0
    total_unchanged: int = 0
    per_debtor: list[DebtorSyncResult] = []
    error: str | None = None


async def _sync_one_debtor(
    integ: Integration, debtor_id: str, debtor_name: str,
    org_id: UUID, db,
) -> DebtorSyncResult:
    """Sync medewerkers voor één debtor. Vangt fouten af zodat
    één kapotte debtor de andere niet meeneemt."""
    result = DebtorSyncResult(
        debtor_id=debtor_id, debtor_name=debtor_name, ok=False,
    )

    client = NmbrsClient(integ, debtor_id, db)
    try:
        companies = await client.companies()
    except NmbrsAuthError as e:
        result.error = str(e)[:200]
        return result
    except Exception as e:
        result.error = f"companies fetch: {type(e).__name__}: {str(e)[:160]}"
        return result

    result.companies_seen = len(companies)

    for company in companies:
        cid = company.get("companyId") or company.get("id")
        if not cid:
            continue
        cid = str(cid)
        try:
            employees_raw = await client.employees(cid)
        except Exception:
            continue

        for emp in employees_raw:
            nmbrs_emp_id = emp.get("employeeId") or emp.get("id")
            if not nmbrs_emp_id:
                continue
            nmbrs_emp_id = str(nmbrs_emp_id)

            basic = emp.get("employeeBasicInfo") or {}
            first = (basic.get("firstName") or "").strip()
            last = (basic.get("lastName") or "").strip()
            prefix = (basic.get("prefix") or "").strip()
            email = None
            role = None

            detail = await client.employee_detail(nmbrs_emp_id)
            if detail:
                pi = detail.get("personalInfo") or {}
                contact = pi.get("contactInfo") or {}
                email = (
                    contact.get("businessEmail") or contact.get("privateEmail") or ""
                ).strip().lower() or None
                bi = pi.get("basicInfo") or {}
                first = (bi.get("firstName") or first or "").strip()
                last = (bi.get("lastName") or last or "").strip()
                prefix = (bi.get("prefix") or prefix or "").strip()
                fn = detail.get("function") or {}
                if isinstance(fn, dict):
                    role = (fn.get("description") or fn.get("name") or "").strip() or None

            full = " ".join(p for p in [first, prefix, last] if p)
            if not full:
                result.skipped_no_name += 1
                continue

            existing = (
                await db.execute(
                    select(Employee).where(
                        Employee.nmbrs_employee_id == nmbrs_emp_id
                    )
                )
            ).scalar_one_or_none()

            now = datetime.now(UTC)
            if existing:
                changed = False
                if existing.full_name != full:
                    existing.full_name = full; changed = True
                if email and existing.email != email:
                    existing.email = email; changed = True
                if existing.nmbrs_company_id != cid:
                    existing.nmbrs_company_id = cid; changed = True
                if role and not existing.role:
                    existing.role = role; changed = True
                if changed:
                    existing.updated_at = now
                    result.employees_updated += 1
                else:
                    result.employees_unchanged += 1
            else:
                db.add(Employee(
                    id=uuid4(), org_id=org_id,
                    full_name=full, email=email, role=role, status="active",
                    nmbrs_employee_id=nmbrs_emp_id,
                    nmbrs_company_id=cid,
                    created_at=now, updated_at=now,
                ))
                result.employees_created += 1

    result.ok = True
    return result


@router.post("/sync-employees", response_model=SyncResult)
async def sync_employees(auth: CurrentAuth, db: Db) -> SyncResult:
    """Sync medewerkers voor ALLE gekoppelde debtors."""
    integ = (
        await db.execute(select(Integration).where(Integration.kind == "nmbrs"))
    ).scalar_one_or_none()
    if not integ:
        raise HTTPException(status_code=400, detail="NMBRS not configured")

    debtors_dict = get_debtors(integ)
    # Skip __legacy__ — die debtor is een onbekende ID en kan niet meer werken
    debtors_to_sync = {
        did: d for did, d in debtors_dict.items()
        if did != "__legacy__" and d.get("refresh_token")
    }

    if not debtors_to_sync:
        return SyncResult(
            ok=False,
            error="Geen actieve debtor-koppelingen. Klik op 'Verbinden met NMBRS' om een debtor te koppelen.",
        )

    per_debtor: list[DebtorSyncResult] = []
    for did, d in debtors_to_sync.items():
        r = await _sync_one_debtor(integ, did, d.get("name", "Unknown"), auth.org_id, db)
        per_debtor.append(r)

    total_created = sum(r.employees_created for r in per_debtor)
    total_updated = sum(r.employees_updated for r in per_debtor)
    total_unchanged = sum(r.employees_unchanged for r in per_debtor)

    integ.last_sync_at = datetime.now(UTC)
    integ.last_sync_status = "ok" if all(r.ok for r in per_debtor) else "partial"
    integ.last_sync_message = (
        f"multi-debtor sync: {total_created} new, {total_updated} updated "
        f"over {len(per_debtor)} debtor(s)"
    )
    await db.flush()

    return SyncResult(
        ok=all(r.ok for r in per_debtor),
        debtors_synced=len(per_debtor),
        total_created=total_created,
        total_updated=total_updated,
        total_unchanged=total_unchanged,
        per_debtor=per_debtor,
    )
