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
    store_debtor_tokens, get_debtors, fetch_debtors_for_token,
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

    # Detecteer ALLE debtors die deze token kan zien.
    # Eén NMBRS-token kan meerdere debtors zien als de gebruiker
    # rechten heeft op meerdere -- we slaan dezelfde token-set op
    # onder elke debtor-key zodat sync over alle debtors kan lopen.
    cfg = integ.config_json or {}
    debtors_found = await fetch_debtors_for_token(
        token_response["access_token"], cfg.get("subscription_key", ""),
    )
    if not debtors_found:
        return back(False, "debtor_detect_failed")

    for debtor_id, debtor_name in debtors_found:
        store_debtor_tokens(integ, debtor_id, debtor_name, token_response)
    integ.is_enabled = True
    await db.commit()

    msg = f"connected_{len(debtors_found)}_debtor(s)"
    return back(True, msg)


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
            emp_number_raw = basic.get("employeeNumber")
            try:
                emp_number = int(emp_number_raw) if emp_number_raw is not None else None
            except (ValueError, TypeError):
                emp_number = None
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
                if emp_number is not None and existing.nmbrs_employee_number != emp_number:
                    existing.nmbrs_employee_number = emp_number; changed = True
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
                    nmbrs_employee_number=emp_number,
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


# ----- SOAP credentials (voor verlof-sync) ---------------------------


class SoapCredsIn(BaseModel):
    username: str
    token: str


class SoapCredsStatus(BaseModel):
    configured: bool
    username: str | None


@router.get("/soap-creds", response_model=SoapCredsStatus)
async def get_soap_creds_status(auth: CurrentAuth, db: Db) -> SoapCredsStatus:
    """Check of SOAP-creds zijn ingevuld (waarde zelf niet terug-gestuurd)."""
    integ = (
        await db.execute(select(Integration).where(Integration.kind == "nmbrs"))
    ).scalar_one_or_none()
    if not integ:
        return SoapCredsStatus(configured=False, username=None)
    cfg = integ.config_json or {}
    user = cfg.get("soap_username")
    has_token = bool(cfg.get("soap_token"))
    return SoapCredsStatus(configured=bool(user and has_token), username=user)


@router.put("/soap-creds")
async def set_soap_creds(
    auth: CurrentAuth, db: Db, data: SoapCredsIn,
) -> dict:
    """Sla SOAP-credentials op."""
    integ = (
        await db.execute(select(Integration).where(Integration.kind == "nmbrs"))
    ).scalar_one_or_none()
    if not integ:
        raise HTTPException(status_code=400, detail="NMBRS not configured")
    cfg = dict(integ.config_json or {})
    cfg["soap_username"] = data.username.strip()
    cfg["soap_token"] = data.token.strip()
    integ.config_json = cfg
    await db.flush()
    return {"ok": True}


@router.delete("/soap-creds")
async def clear_soap_creds(auth: CurrentAuth, db: Db) -> dict:
    integ = (
        await db.execute(select(Integration).where(Integration.kind == "nmbrs"))
    ).scalar_one_or_none()
    if not integ:
        raise HTTPException(status_code=400, detail="NMBRS not configured")
    cfg = dict(integ.config_json or {})
    cfg.pop("soap_username", None)
    cfg.pop("soap_token", None)
    integ.config_json = cfg
    await db.flush()
    return {"ok": True}


# ----- Sync absences (verlof) ----------------------------------------


class AbsenceSyncResult(BaseModel):
    ok: bool
    employees_with_absences: int = 0
    absences_total: int = 0
    appointments_created: int = 0
    appointments_deleted: int = 0
    appointments_skipped_duplicate: int = 0
    skipped_no_match: list[str] = []
    error: str | None = None


@router.post("/sync-absences", response_model=AbsenceSyncResult)
async def sync_absences(auth: CurrentAuth, db: Db) -> AbsenceSyncResult:
    """User-facing endpoint: absence-sync voor huidige org."""
    return await _run_absence_sync(auth.org_id, db)


async def _run_absence_sync(org_id: UUID, db) -> AbsenceSyncResult:
    """Haal NMBRS verlof + ziekte op en sync naar HaloPSA Appointment.

    Twee bronnen per medewerker:
      1. SOAP Absence_GetAll_AllEmployeesByCompany -- bulk ziekte per company
      2. SOAP Leave_GetList per employee -- vakantie/verlof (geen bulk endpoint)

    Privacy: subject altijd 'NMBRS: Afwezig'. Geen type/comment leak.

    Idempotent + DELETE-flow:
      - Per sync wordt een set met "currently active" business_keys
        opgebouwd uit NMBRS.
      - Bestaande synced_absences rows die NIET in die set zitten ->
        DELETE op HaloPSA + markeer deleted_at.
      - Nieuwe records die nog niet in DB staan -> POST en INSERT.
      - Dedup via UniqueConstraint(org_id, source, business_key).

    "Blijvend negeren":
      - Employee zonder halopsa_agent_id wordt stilletjes overgeslagen
        (NIET in skipped_no_match return).
      - Alleen echt onverwachte issues (POST mislukt, employee niet
        gevonden via SOAP) verschijnen in skipped_no_match.
    """
    from uuid import uuid4
    from salespilot.integrations.nmbrs_soap import (
        NmbrsSoapCreds, NmbrsSoapError, fetch_all_absences,
        environment_get, parse_nmbrs_date, is_fullday_absence,
        leave_for_employee, leave_business_key, absence_business_key,
    )
    from salespilot.integrations.halopsa import HaloPSAClient, HaloPSACredentials
    from salespilot.models.absences import SyncedAbsence
    from salespilot.models.inventory import Employee

    integ = (
        await db.execute(select(Integration).where(Integration.kind == "nmbrs"))
    ).scalar_one_or_none()
    if not integ:
        raise HTTPException(status_code=400, detail="NMBRS not configured")
    cfg = integ.config_json or {}
    soap_user = cfg.get("soap_username")
    soap_token = cfg.get("soap_token")
    if not soap_user or not soap_token:
        return AbsenceSyncResult(
            ok=False,
            error="SOAP-credentials ontbreken. Vul ze in bij Settings > NMBRS.",
        )

    halo_integ = (
        await db.execute(select(Integration).where(Integration.kind == "halopsa"))
    ).scalar_one_or_none()
    if not halo_integ:
        return AbsenceSyncResult(ok=False, error="HaloPSA not configured")
    halo_cfg = halo_integ.config_json

    # SOAP creds + domain (Environment_Get)
    creds = NmbrsSoapCreds(
        username=soap_user, token=soap_token,
        domain=cfg.get("soap_domain", ""),
    )
    if not creds.domain:
        try:
            sub = await environment_get(creds)
        except NmbrsSoapError as e:
            return AbsenceSyncResult(
                ok=False, error=f"Environment_Get faalde: {str(e)[:160]}",
            )
        if not sub:
            return AbsenceSyncResult(ok=False, error="Kon NMBRS subdomain niet ontdekken")
        creds.domain = sub
        new_cfg = dict(cfg); new_cfg["soap_domain"] = sub
        integ.config_json = new_cfg
        await db.flush()

    # Fetch absences + SOAP employee-mapping
    try:
        all_abs, all_soap_emps = await fetch_all_absences(creds)
    except NmbrsSoapError as e:
        return AbsenceSyncResult(ok=False, error=f"SOAP error: {str(e)[:200]}")

    employees = (
        await db.execute(select(Employee))
    ).scalars().all()

    # SOAP-mapping: SOAP id -> Number, en Number -> Employee
    soap_by_name: dict[str, int] = {}
    soap_id_to_number: dict[int, int] = {}
    number_to_soap_id: dict[int, int] = {}
    for se in all_soap_emps:
        name = (se.get("DisplayName") or "").strip()
        num_raw = se.get("Number"); id_raw = se.get("Id")
        try:
            num = int(num_raw) if num_raw else None
        except (ValueError, TypeError):
            num = None
        try:
            sid = int(id_raw) if id_raw else None
        except (ValueError, TypeError):
            sid = None
        if num and name:
            soap_by_name[name.lower()] = num
        if num and sid:
            soap_id_to_number[sid] = num
            number_to_soap_id[num] = sid

    # Vul nmbrs_employee_number waar ie nog ontbreekt
    for e in employees:
        if e.nmbrs_employee_number is None and e.full_name:
            n = soap_by_name.get(e.full_name.lower())
            if n is not None:
                e.nmbrs_employee_number = n
    await db.flush()

    # Map Number -> Employee
    emp_by_number: dict[int, Employee] = {
        e.nmbrs_employee_number: e
        for e in employees if e.nmbrs_employee_number is not None
    }

    halo_creds = HaloPSACredentials(
        base_url=halo_cfg.get("base_url", ""),
        client_id=halo_cfg.get("client_id", ""),
        client_secret=halo_cfg.get("client_secret", ""),
        tenant_id=halo_cfg.get("tenant_id"),
    )

    # Verzamel "active set" van business_keys uit NMBRS deze sync.
    # Buiten deze set staande synced_absences -> deleten.
    active_keys: set[str] = set()
    # Per business_key: meta die we straks willen schrijven als 't nieuw is
    new_records: list[dict] = []
    skipped_problems: list[str] = []
    silently_skipped_no_agent = 0
    employees_with_records: set = set()

    # --- 1. Ziekte uit Absence_GetAll_AllEmployeesByCompany --------

    for a in all_abs:
        nmbrs_abs_id_raw = a.get("AbsenceId")
        if not nmbrs_abs_id_raw:
            continue
        try:
            nmbrs_abs_id = int(nmbrs_abs_id_raw)
        except (ValueError, TypeError):
            continue
        emp_soap_id_raw = a.get("EmployeeId")
        try:
            emp_soap_id = int(emp_soap_id_raw) if emp_soap_id_raw else None
        except (ValueError, TypeError):
            emp_soap_id = None
        emp_number = soap_id_to_number.get(emp_soap_id) if emp_soap_id else None
        emp = emp_by_number.get(emp_number) if emp_number else None

        if emp is None:
            # Echt iets fout (SOAP-id niet matchbaar)
            skipped_problems.append(
                f"abs_id={nmbrs_abs_id}: SOAP emp_id {emp_soap_id} niet in SalesPilot"
            )
            continue

        employees_with_records.add(emp.id)

        # Blijvend negeren als geen halopsa_agent_id
        if not emp.halopsa_agent_id:
            silently_skipped_no_agent += 1
            continue

        start_dt = parse_nmbrs_date(a.get("Start"))
        end_dt = parse_nmbrs_date(a.get("End"))
        if not start_dt:
            continue
        if not end_dt:
            end_dt = start_dt

        bkey = absence_business_key(nmbrs_abs_id)
        if bkey in active_keys:
            continue
        active_keys.add(bkey)
        new_records.append({
            "source": "absence",
            "business_key": bkey,
            "nmbrs_absence_id": nmbrs_abs_id,
            "employee": emp,
            "start_dt": start_dt,
            "end_dt": end_dt,
            "company_id": str(a.get("_company_id") or "") or None,
        })

    # --- 2. Vakantie/verlof uit Leave_GetList per employee --------

    from datetime import datetime as _dt
    current_year = _dt.now().year
    # Alleen huidig + vorig + volgend jaar; alleen voor employees met halopsa_agent_id
    years_to_check = [current_year - 1, current_year, current_year + 1]
    for emp in employees:
        if not emp.halopsa_agent_id:
            continue
        if not emp.nmbrs_employee_number:
            continue
        soap_id = number_to_soap_id.get(emp.nmbrs_employee_number)
        if not soap_id:
            continue
        for year in years_to_check:
            try:
                leaves = await leave_for_employee(creds, soap_id, year)
            except NmbrsSoapError:
                continue
            for lv in leaves:
                start_raw = lv.get("Start") or ""
                end_raw = lv.get("End") or start_raw
                hours = lv.get("Hours") or ""
                description = lv.get("Description") or ""
                bkey = leave_business_key(
                    emp.nmbrs_employee_id or str(emp.id),
                    start_raw, end_raw, hours, description,
                )
                start_dt = parse_nmbrs_date(start_raw)
                end_dt = parse_nmbrs_date(end_raw)
                if not start_dt:
                    continue
                if not end_dt:
                    end_dt = start_dt

                # StartHours/EndHours kunnen aangeven dat het een dagdeel is.
                # 8.00 / 8.00 = hele dag; 4.00 = halve dag.
                start_hours = lv.get("StartHours") or "8.00"
                end_hours = lv.get("EndHours") or "8.00"

                if bkey in active_keys:
                    continue  # zelfde leave-record kwam al via andere year
                active_keys.add(bkey)
                employees_with_records.add(emp.id)
                new_records.append({
                    "source": "leave",
                    "business_key": bkey,
                    "nmbrs_absence_id": None,
                    "employee": emp,
                    "start_dt": start_dt,
                    "end_dt": end_dt,
                    "company_id": None,
                    "start_hours": start_hours,
                    "end_hours": end_hours,
                    "hours_total": hours,
                })

    # --- 3. Bepaal welke records nieuw zijn vs al gesynced --------

    existing_records = (
        await db.execute(
            select(SyncedAbsence).where(
                SyncedAbsence.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    existing_by_key = {s.business_key: s for s in existing_records}

    created = 0
    skipped_dup = 0
    deleted = 0

    async with HaloPSAClient(halo_creds) as halo_client:
        # --- 3a. Aanmaken van nieuwe records ---
        for rec in new_records:
            if rec["business_key"] in existing_by_key:
                skipped_dup += 1
                continue

            emp = rec["employee"]
            start_dt = rec["start_dt"]
            end_dt = rec["end_dt"]

            # Allday-bepaling
            # Voor Leave: kijk naar StartHours/EndHours -- 8.00 = hele dag, lager = dagdeel
            if rec["source"] == "leave":
                sh = float(rec.get("start_hours") or 8.0)
                eh = float(rec.get("end_hours") or 8.0)
                # Halve dag (4u) -> allday=False, blok 's ochtends (08:30-12:30)
                # of 's middags (13:00-17:00). Zonder uur-info: 's ochtends default.
                full_day = sh >= 7.5 and eh >= 7.5
                allday = full_day
            else:
                allday = is_fullday_absence(start_dt, end_dt)

            if allday:
                start_str = start_dt.strftime("%Y-%m-%dT00:00:00")
                end_str = end_dt.strftime("%Y-%m-%dT23:59:00")
            else:
                # Halve dag: ochtend
                start_str = start_dt.strftime("%Y-%m-%dT08:30:00")
                end_str = end_dt.strftime("%Y-%m-%dT12:30:00")

            halo_body = {
                "agent_id": emp.halopsa_agent_id,
                "subject": "NMBRS: Afwezig",
                "start_date": start_str,
                "end_date": end_str,
                "allday": allday,
                "colour": "#6b7280",
                "appointment_type_name": "Reminder",
            }
            try:
                halo_resp = await halo_client._request(
                    "POST", "/api/Appointment", json=[halo_body],
                )
            except Exception as e:
                skipped_problems.append(
                    f"{emp.full_name}: HaloPSA POST mislukt -- {str(e)[:80]}"
                )
                continue

            halo_appt_id = None
            if isinstance(halo_resp, dict):
                halo_appt_id = halo_resp.get("id")
            elif isinstance(halo_resp, list) and halo_resp:
                halo_appt_id = halo_resp[0].get("id") if isinstance(halo_resp[0], dict) else None

            db.add(SyncedAbsence(
                id=uuid4(), org_id=org_id,
                employee_id=emp.id,
                nmbrs_absence_id=rec["nmbrs_absence_id"],
                business_key=rec["business_key"],
                source=rec["source"],
                nmbrs_company_id=rec.get("company_id"),
                halopsa_appointment_id=halo_appt_id,
                absence_type_code="absent",
                absence_type_label="Afwezig",
                start_date=start_dt.date(),
                end_date=end_dt.date(),
                percentage=None, comment=None,
                subject="NMBRS: Afwezig",
                last_modified_at=None,
                synced_at=datetime.now(UTC),
            ))
            created += 1
            await db.flush()

        # --- 3b. DELETE-flow voor records die niet meer in NMBRS staan ---
        for s in existing_records:
            if s.business_key in active_keys:
                continue
            # Niet meer in NMBRS -> delete uit HaloPSA + markeer
            if s.halopsa_appointment_id:
                try:
                    await halo_client._request(
                        "DELETE", f"/api/Appointment/{s.halopsa_appointment_id}",
                    )
                except Exception as e:
                    # Als de appointment al weg is uit HaloPSA (handmatig), prima
                    if "404" not in str(e):
                        skipped_problems.append(
                            f"DELETE {s.halopsa_appointment_id} mislukt: {str(e)[:80]}"
                        )
                        continue
            s.deleted_at = datetime.now(UTC)
            deleted += 1
            await db.flush()

    integ.last_sync_at = datetime.now(UTC)
    integ.last_sync_status = "ok"
    integ.last_sync_message = (
        f"sync: {created} aangemaakt, {deleted} verwijderd, "
        f"{skipped_dup} ongewijzigd, {silently_skipped_no_agent} stil overgeslagen (geen agent)"
    )
    await db.flush()

    return AbsenceSyncResult(
        ok=True,
        employees_with_absences=len(employees_with_records),
        absences_total=len(new_records),
        appointments_created=created,
        appointments_deleted=deleted,
        appointments_skipped_duplicate=skipped_dup,
        skipped_no_match=skipped_problems[:50],
    )

