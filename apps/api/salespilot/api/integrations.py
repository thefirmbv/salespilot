"""Integrations endpoints.

  GET  /integrations                        connector summary for the grid
  GET  /integrations/halopsa                read HaloPSA config
  PUT  /integrations/halopsa                upsert HaloPSA config
  POST /integrations/halopsa/test           test HaloPSA connection
  POST /integrations/halopsa/sync           pull clients into companies
  GET  /integrations/prospectpro            read ProspectPRO config
  PUT  /integrations/prospectpro            upsert ProspectPRO config
  POST /integrations/prospectpro/test       test ProspectPRO connection
  POST /integrations/prospectpro/sync       pull prospects + pageviews
  GET  /integrations/anthropic              read Anthropic config
  PUT  /integrations/anthropic              upsert Anthropic config
  POST /integrations/anthropic/test         test Anthropic key
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from salespilot.deps import CurrentAuth, Db
from salespilot.integrations.callscript import (
    generate_callscript,
    scrape_website_summary,
)
from salespilot.integrations.halopsa import (
    HaloPSAClient,
    HaloPSACredentials,
    HaloPSAError,
)
from salespilot.integrations.mx import detect_mail_platform
from salespilot.integrations.prospectpro import (
    ProspectPROClient,
    ProspectPROCredentials,
    ProspectPROError,
)
from salespilot.integrations.scoring import compute_score
from salespilot.models.crm import Company, CompanySource, MailPlatform
from salespilot.models.integrations import Integration
from salespilot.models.visitor import VisitorEvent
from salespilot.schemas.integrations import (
    Callscript,
    IntegrationPublic,
    IntegrationSummary,
    IntegrationUpsert,
    SyncResult,
    TestConnectionResult,
)

router = APIRouter(prefix="/integrations", tags=["integrations"])
companies_extra_router = APIRouter(prefix="/companies", tags=["companies"])


HALOPSA_KIND = "halopsa"
PROSPECTPRO_KIND = "prospectpro"
ANTHROPIC_KIND = "anthropic"


def _public_config(kind: str, cfg: dict[str, Any]) -> dict[str, Any]:
    if kind == HALOPSA_KIND:
        return {
            "base_url": cfg.get("base_url"),
            "client_id": cfg.get("client_id"),
            "tenant": cfg.get("tenant"),
            "scopes": cfg.get("scopes"),
            "client_secret_set": bool(cfg.get("client_secret")),
        }
    if kind == PROSPECTPRO_KIND:
        return {
            "base_url": cfg.get("base_url") or "api.prospectpro.nl",
            "api_key_set": bool(cfg.get("api_key")),
        }
    if kind == ANTHROPIC_KIND:
        return {
            "model": cfg.get("model") or "claude-sonnet-4-5-20250929",
            "api_key_set": bool(cfg.get("api_key")),
        }
    return {}


def _to_public(row: Integration) -> IntegrationPublic:
    return IntegrationPublic(
        id=row.id,
        kind=row.kind,
        is_enabled=row.is_enabled,
        config_public=_public_config(row.kind, row.config_json or {}),
        last_sync_at=row.last_sync_at,
        last_sync_status=row.last_sync_status,
        last_sync_message=row.last_sync_message,
        updated_at=row.updated_at,
    )


async def _get_integration(db, kind: str) -> Integration | None:
    res = await db.execute(select(Integration).where(Integration.kind == kind))
    return res.scalar_one_or_none()


@router.get("", response_model=list[IntegrationSummary])
async def list_integrations(db: Db) -> list[IntegrationSummary]:
    rows = (await db.execute(select(Integration))).scalars().all()
    by_kind = {r.kind: r for r in rows}
    known = [
        (HALOPSA_KIND, "HaloPSA", "PSA / ticketing — read clients, push prospects, fetch quotations"),
        (PROSPECTPRO_KIND, "ProspectPRO", "B2B prospect database + website visitor identification"),
        (ANTHROPIC_KIND, "Anthropic (Claude)", "AI-generated callscripts on the prospect detail page"),
    ]
    out: list[IntegrationSummary] = []
    for kind, label, desc in known:
        row = by_kind.get(kind)
        extra: dict[str, Any] = {}
        if kind == HALOPSA_KIND and row:
            extra["base_url"] = (row.config_json or {}).get("base_url")
        if kind == ANTHROPIC_KIND and row:
            extra["model"] = (row.config_json or {}).get("model")
        out.append(IntegrationSummary(
            kind=kind, label=label, description=desc,
            is_configured=row is not None,
            is_enabled=bool(row and row.is_enabled),
            last_sync_at=row.last_sync_at if row else None,
            last_sync_status=row.last_sync_status if row else None,
            extra=extra,
        ))
    return out


def _make_kind_routes(kind: str):
    @router.get(f"/{kind}", response_model=IntegrationPublic | None)
    async def get_integration(auth: CurrentAuth, db: Db) -> IntegrationPublic | None:
        row = await _get_integration(db, kind)
        return _to_public(row) if row else None

    @router.put(f"/{kind}", response_model=IntegrationPublic)
    async def upsert_integration(data: IntegrationUpsert, auth: CurrentAuth, db: Db) -> IntegrationPublic:
        row = await _get_integration(db, kind)
        cfg_dict = dict(data.config or {})
        secret_keys = ("client_secret", "api_key")
        if row is not None:
            existing = row.config_json or {}
            for sk in secret_keys:
                if not cfg_dict.get(sk):
                    cfg_dict[sk] = existing.get(sk, "")
            row.is_enabled = data.is_enabled
            row.config_json = cfg_dict
        else:
            row = Integration(
                id=uuid4(), org_id=auth.org_id, kind=kind,
                is_enabled=data.is_enabled, config_json=cfg_dict,
            )
            db.add(row)
        await db.flush()
        await db.refresh(row)
        return _to_public(row)


_make_kind_routes(HALOPSA_KIND)
_make_kind_routes(PROSPECTPRO_KIND)
_make_kind_routes(ANTHROPIC_KIND)


# ---- HaloPSA test/sync ----


def _halopsa_creds(row: Integration) -> HaloPSACredentials:
    cfg = row.config_json or {}
    return HaloPSACredentials(
        base_url=cfg.get("base_url", ""),
        client_id=cfg.get("client_id", ""),
        client_secret=cfg.get("client_secret", ""),
        tenant=cfg.get("tenant"),
        scopes=cfg.get("scopes") or "all",
    )


@router.post(f"/{HALOPSA_KIND}/test", response_model=TestConnectionResult)
async def test_halopsa(auth: CurrentAuth, db: Db) -> TestConnectionResult:
    row = await _get_integration(db, HALOPSA_KIND)
    if row is None:
        raise HTTPException(status_code=400, detail="HaloPSA not configured yet")
    try:
        async with HaloPSAClient(_halopsa_creds(row)) as client:
            await client.test_connection()
        return TestConnectionResult(ok=True, detail="Authenticated successfully.", token_present=True)
    except HaloPSAError as e:
        return TestConnectionResult(ok=False, detail=str(e))


def _map_halopsa_client(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": c.get("name") or "Unnamed",
        "domain": c.get("website") or None,
        "industry": c.get("sector_name") or c.get("sector") or None,
        "description": c.get("notes") or None,
    }


@router.post(f"/{HALOPSA_KIND}/sync", response_model=SyncResult)
async def sync_halopsa(auth: CurrentAuth, db: Db) -> SyncResult:
    row = await _get_integration(db, HALOPSA_KIND)
    if row is None or not row.is_enabled:
        raise HTTPException(status_code=400, detail="HaloPSA not configured or disabled")
    try:
        async with HaloPSAClient(_halopsa_creds(row)) as client:
            clients = await client.list_clients()
    except HaloPSAError as e:
        row.last_sync_at = datetime.now(UTC)
        row.last_sync_status = "error"
        row.last_sync_message = str(e)[:1000]
        await db.flush()
        return SyncResult(ok=False, detail=str(e))

    existing = (
        await db.execute(select(Company).where(Company.halopsa_id.is_not(None)))
    ).scalars().all()
    by_id: dict[int, Company] = {c.halopsa_id: c for c in existing if c.halopsa_id is not None}

    created = 0
    updated = 0
    now = datetime.now(UTC)
    for raw in clients:
        try:
            halopsa_id = int(raw.get("id"))
        except (TypeError, ValueError):
            continue
        mapped = _map_halopsa_client(raw)
        existing_row = by_id.get(halopsa_id)
        if existing_row:
            for k, v in mapped.items():
                setattr(existing_row, k, v)
            existing_row.source = CompanySource.HALOPSA
            existing_row.halopsa_synced_at = now
            updated += 1
        else:
            db.add(Company(
                id=uuid4(), org_id=auth.org_id,
                name=mapped["name"], domain=mapped["domain"],
                industry=mapped["industry"], description=mapped["description"],
                source=CompanySource.HALOPSA, halopsa_id=halopsa_id,
                halopsa_synced_at=now,
            ))
            created += 1

    row.last_sync_at = now
    row.last_sync_status = "ok"
    row.last_sync_message = f"Fetched {len(clients)} clients"
    await db.flush()
    return SyncResult(
        ok=True,
        detail=f"Synced {len(clients)} clients ({created} new, {updated} updated)",
        fetched=len(clients), created=created, updated=updated,
    )


# ---- ProspectPRO ----


def _prospectpro_creds(row: Integration) -> ProspectPROCredentials:
    cfg = row.config_json or {}
    return ProspectPROCredentials(
        base_url=cfg.get("base_url") or "api.prospectpro.nl",
        api_key=cfg.get("api_key") or "",
    )


@router.post(f"/{PROSPECTPRO_KIND}/test", response_model=TestConnectionResult)
async def test_prospectpro(auth: CurrentAuth, db: Db) -> TestConnectionResult:
    row = await _get_integration(db, PROSPECTPRO_KIND)
    if row is None:
        raise HTTPException(status_code=400, detail="ProspectPRO not configured yet")
    try:
        async with ProspectPROClient(_prospectpro_creds(row)) as client:
            await client.test_connection()
        return TestConnectionResult(ok=True, detail="Authenticated successfully.", token_present=True)
    except ProspectPROError as e:
        return TestConnectionResult(ok=False, detail=str(e))


def _map_prospectpro_prospect(p: dict[str, Any]) -> dict[str, Any]:
    employees = None
    for key in ("employees", "employee_count", "personnel"):
        val = p.get(key)
        if isinstance(val, int):
            employees = val
            break
        if isinstance(val, str) and val.isdigit():
            employees = int(val)
            break
    country = (p.get("country_code") or p.get("country") or "NL")
    return {
        "name": p.get("name") or p.get("company_name") or "Unnamed",
        "domain": p.get("website") or p.get("domain"),
        "industry": p.get("industry") or p.get("sector") or p.get("sbi_description"),
        "employees": employees,
        "city": p.get("city") or p.get("address_city"),
        "country": country[:2].upper() if isinstance(country, str) and country else "NL",
        "description": p.get("description") or p.get("about") or None,
    }


def _parse_pp_datetime(s: Any) -> datetime | None:
    if not s or not isinstance(s, str):
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        return None


@router.post(f"/{PROSPECTPRO_KIND}/sync", response_model=SyncResult)
async def sync_prospectpro(auth: CurrentAuth, db: Db) -> SyncResult:
    row = await _get_integration(db, PROSPECTPRO_KIND)
    if row is None or not row.is_enabled:
        raise HTTPException(status_code=400, detail="ProspectPRO not configured or disabled")
    try:
        async with ProspectPROClient(_prospectpro_creds(row)) as client:
            prospects = await client.list_prospects()
            pv_by_prospect: dict[str, list[dict[str, Any]]] = {}
            for p in prospects:
                pid = str(p.get("id") or p.get("prospect_id") or "")
                if not pid:
                    continue
                if (p.get("type") in {"visitor", "warm"} or p.get("is_visitor") or p.get("pageview_count")):
                    try:
                        pv_by_prospect[pid] = await client.list_pageviews_for_prospect(pid)
                    except ProspectPROError:
                        pv_by_prospect[pid] = []
    except ProspectPROError as e:
        row.last_sync_at = datetime.now(UTC)
        row.last_sync_status = "error"
        row.last_sync_message = str(e)[:1000]
        await db.flush()
        return SyncResult(ok=False, detail=str(e))

    now = datetime.now(UTC)
    thirty_days_ago = now - timedelta(days=30)
    existing_rows = (
        await db.execute(select(Company).where(Company.prospectpro_id.is_not(None)))
    ).scalars().all()
    by_pp_id: dict[str, Company] = {c.prospectpro_id: c for c in existing_rows if c.prospectpro_id}

    created = 0
    updated = 0
    for p in prospects:
        pid = str(p.get("id") or p.get("prospect_id") or "")
        if not pid:
            continue
        mapped = _map_prospectpro_prospect(p)
        existing_row = by_pp_id.get(pid)
        if existing_row is None:
            existing_row = Company(
                id=uuid4(), org_id=auth.org_id,
                source=CompanySource.SALESPILOT, prospectpro_id=pid, **mapped,
            )
            db.add(existing_row)
            await db.flush()
            created += 1
        else:
            for k, v in mapped.items():
                if v is not None:
                    setattr(existing_row, k, v)
            updated += 1
        existing_row.prospectpro_synced_at = now

        pageviews = pv_by_prospect.get(pid, [])
        recent_pv_urls: list[str] = []
        recent_pv_dates: list[datetime] = []
        last_visit: datetime | None = None
        for pv in pageviews:
            occurred = _parse_pp_datetime(pv.get("occurred_at") or pv.get("date") or pv.get("created_at"))
            if occurred is None:
                continue
            url = pv.get("url") or pv.get("page_url") or ""
            ext_id = str(pv.get("id") or "")
            if ext_id:
                existing_event_q = await db.execute(
                    select(VisitorEvent).where(
                        VisitorEvent.source == "prospectpro",
                        VisitorEvent.external_id == ext_id,
                    )
                )
                if existing_event_q.scalar_one_or_none() is None:
                    db.add(VisitorEvent(
                        id=uuid4(), org_id=auth.org_id, company_id=existing_row.id,
                        source="prospectpro", external_id=ext_id, event_type="pageview",
                        url=url, page_title=pv.get("title") or pv.get("page_title"),
                        referrer=pv.get("referrer"), occurred_at=occurred,
                        raw=pv, created_at=now,
                    ))
            if occurred >= thirty_days_ago:
                recent_pv_urls.append(url)
                recent_pv_dates.append(occurred)
            if last_visit is None or occurred > last_visit:
                last_visit = occurred

        if last_visit is not None:
            existing_row.last_visit_at = last_visit
            existing_row.pageview_count_30d = len(recent_pv_dates)

        score, _ = compute_score(
            employees=existing_row.employees,
            mail_platform=existing_row.mail_platform.value if existing_row.mail_platform else "unknown",
            pageview_urls=recent_pv_urls, pageview_dates=recent_pv_dates,
            last_visit_at=existing_row.last_visit_at,
        )
        existing_row.lead_score = score

    row.last_sync_at = now
    row.last_sync_status = "ok"
    row.last_sync_message = f"Fetched {len(prospects)} prospects"
    await db.flush()
    return SyncResult(
        ok=True, detail=f"Synced {len(prospects)} prospects ({created} new, {updated} updated)",
        fetched=len(prospects), created=created, updated=updated,
    )


# ---- Anthropic test ----


@router.post(f"/{ANTHROPIC_KIND}/test", response_model=TestConnectionResult)
async def test_anthropic(auth: CurrentAuth, db: Db) -> TestConnectionResult:
    row = await _get_integration(db, ANTHROPIC_KIND)
    if row is None:
        raise HTTPException(status_code=400, detail="Anthropic not configured yet")
    cfg = row.config_json or {}
    api_key = cfg.get("api_key", "")
    if not api_key:
        return TestConnectionResult(ok=False, detail="API key is empty")
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key, "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": cfg.get("model") or "claude-sonnet-4-5-20250929",
                    "max_tokens": 4, "messages": [{"role": "user", "content": "ping"}],
                },
            )
    except httpx.HTTPError as e:
        return TestConnectionResult(ok=False, detail=str(e))
    if res.status_code in (401, 403):
        return TestConnectionResult(ok=False, detail="Authentication failed — bad API key?")
    if res.status_code >= 400:
        return TestConnectionResult(ok=False, detail=f"Anthropic returned {res.status_code}: {res.text[:200]}")
    return TestConnectionResult(ok=True, detail="API key is valid.", token_present=True)


# ---- Company-scoped routes ----


@companies_extra_router.post("/{company_id}/push-to-halopsa", response_model=dict[str, Any])
async def push_to_halopsa(company_id: UUID, auth: CurrentAuth, db: Db) -> dict[str, Any]:
    integ = await _get_integration(db, HALOPSA_KIND)
    if integ is None or not integ.is_enabled:
        raise HTTPException(status_code=400, detail="HaloPSA not configured or disabled")
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="company not found")
    if company.halopsa_id is not None:
        raise HTTPException(status_code=409, detail=f"already linked to HaloPSA client {company.halopsa_id}")
    payload: dict[str, Any] = {"name": company.name, "inactive": False, "main_site_name": "HaloPSA"}
    if company.domain:
        payload["website"] = company.domain
    if company.description:
        payload["notes"] = company.description
    try:
        async with HaloPSAClient(_halopsa_creds(integ)) as client:
            result = await client.create_client(payload)
    except HaloPSAError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    new_id = result.get("id")
    if not isinstance(new_id, int):
        raise HTTPException(status_code=502, detail=f"HaloPSA did not return a client id: {result!r}")
    company.halopsa_id = new_id
    company.source = CompanySource.HALOPSA_PUSHED
    company.halopsa_synced_at = datetime.now(UTC)
    await db.flush()
    return {"halopsa_id": new_id, "source": company.source.value}


@companies_extra_router.get("/{company_id}/halopsa-quotations")
async def list_halopsa_quotations(company_id: UUID, auth: CurrentAuth, db: Db) -> list[dict[str, Any]]:
    integ = await _get_integration(db, HALOPSA_KIND)
    if integ is None or not integ.is_enabled:
        return []
    company = await db.get(Company, company_id)
    if company is None or company.halopsa_id is None:
        return []
    try:
        async with HaloPSAClient(_halopsa_creds(integ)) as client:
            return await client.list_quotations_for_client(company.halopsa_id)
    except HaloPSAError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@companies_extra_router.post("/{company_id}/refresh-mx")
async def refresh_mx(company_id: UUID, auth: CurrentAuth, db: Db) -> dict[str, Any]:
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="company not found")
    if not company.domain:
        return {"platform": "unknown", "detail": "no domain set"}
    result = await detect_mail_platform(company.domain)
    company.mail_platform = MailPlatform(result.platform)
    company.mail_platform_checked_at = datetime.now(UTC)
    await db.flush()
    return {"platform": result.platform, "records": result.records}


@companies_extra_router.post("/{company_id}/callscript", response_model=Callscript)
async def make_callscript(company_id: UUID, auth: CurrentAuth, db: Db) -> Callscript:
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="company not found")

    if (
        company.mail_platform == MailPlatform.UNKNOWN
        or company.mail_platform_checked_at is None
        or (datetime.now(UTC) - company.mail_platform_checked_at) > timedelta(days=7)
    ) and company.domain:
        result = await detect_mail_platform(company.domain)
        company.mail_platform = MailPlatform(result.platform)
        company.mail_platform_checked_at = datetime.now(UTC)

    events = (
        await db.execute(
            select(VisitorEvent)
            .where(VisitorEvent.company_id == company.id)
            .order_by(VisitorEvent.occurred_at.desc())
            .limit(20)
        )
    ).scalars().all()
    pageviews = [
        {"url": e.url, "page_title": e.page_title, "occurred_at": e.occurred_at.isoformat()}
        for e in events
    ]

    anth_row = await _get_integration(db, ANTHROPIC_KIND)
    api_key = (anth_row.config_json or {}).get("api_key") if anth_row else None
    model = ((anth_row.config_json or {}).get("model") if anth_row else None) or "claude-sonnet-4-5-20250929"

    website_summary = await scrape_website_summary(company.domain)

    script = await generate_callscript(
        api_key=api_key, model=model,
        company={
            "id": company.id, "name": company.name, "domain": company.domain,
            "industry": company.industry, "employees": company.employees,
            "city": company.city, "country": company.country,
            "description": company.description, "mail_platform": company.mail_platform.value,
        },
        pageviews=pageviews, website_summary=website_summary,
    )

    company.callscript_json = script.model_dump(mode="json")
    company.callscript_generated_at = script.generated_at
    await db.flush()
    return script
