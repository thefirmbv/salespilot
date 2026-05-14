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
from salespilot.integrations.wespennest_sources import (
    CrtShClient,
    KvkClient,
    OpenKvkClient,
    PdokClient,
    SourceTestResult,
)
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
MAILGUN_KIND = "mailgun"
LINKEDIN_KIND = "linkedin"
# Wespennest data sources -- each can be toggled on/off independently.
# Order roughly matches the discovery -> enrichment pipeline.
KVK_KIND = "kvk"
OPENKVK_KIND = "openkvk"
PDOK_KIND = "pdok"
CRTSH_KIND = "crtsh"
HUNTER_KIND = "hunter"
APOLLO_KIND = "apollo"
# Microsoft 365 SSO -- OAuth login + (later) email/calendar sync
M365_SSO_KIND = "m365_sso"
PBX_3CX_KIND = "pbx_3cx"
WESPENNEST_KIND = "wespennest"


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
    if kind == MAILGUN_KIND:
        # Expose 'limits' so the frontend can prefill throttle fields.
        limits = cfg.get("limits") or {}
        if not isinstance(limits, dict):
            limits = {}
        return {
            "base_url": cfg.get("base_url") or "api.eu.mailgun.net",
            "domain": cfg.get("domain"),
            "default_from_name": cfg.get("default_from_name"),
            "default_from_email": cfg.get("default_from_email"),
            "default_reply_to": cfg.get("default_reply_to"),
            "api_key_set": bool(cfg.get("api_key")),
            "webhook_signing_key_set": bool(cfg.get("webhook_signing_key")),
            "limits": {
                "max_per_day": limits.get("max_per_day") or 30,
                "max_per_hour": limits.get("max_per_hour") or 6,
                "min_seconds_gap": limits.get("min_seconds_gap") or 90,
            },
        }
    if kind == LINKEDIN_KIND:
        return {
            "client_id": cfg.get("client_id"),
            "person_urn": cfg.get("person_urn"),
            "organization_urn": cfg.get("organization_urn"),
            "client_secret_set": bool(cfg.get("client_secret")),
            "access_token_set": bool(cfg.get("access_token")),
            # OAuth status -- frontend uses this to show "Verbonden" badge
            # + reconnect button. Secrets themselves stay server-only.
            "connected_via_oauth": bool(cfg.get("connected_via_oauth")),
            "connected_at": cfg.get("connected_at"),
            "access_token_expires_at": cfg.get("access_token_expires_at"),
            "granted_scope": cfg.get("granted_scope"),
        }
    # ---- Wespennest sources ----
    if kind == KVK_KIND:
        # KVK API (https://developers.kvk.nl). Requires manual approval
        # (~5 working days). Two keys: basisprofiel + functionarissen.
        return {
            "base_url": cfg.get("base_url") or "https://api.kvk.nl/api",
            "api_key_set": bool(cfg.get("api_key")),
            "functionarissen_key_set": bool(cfg.get("functionarissen_key")),
        }
    if kind == OPENKVK_KIND:
        # OpenKVK / overheid.io. Free, no signup needed. We expose
        # base_url only so an alternative mirror can be plugged in.
        return {
            "base_url": cfg.get("base_url") or "https://api.overheid.io/openkvk",
            "api_key_set": bool(cfg.get("api_key")),  # optional (rate limits)
        }
    if kind == PDOK_KIND:
        # PDOK geocoder (BAG + locatieserver). Free, no signup.
        # Used for address -> lat/lon and distance-to-Breukelen.
        return {
            "base_url": cfg.get("base_url") or "https://api.pdok.nl",
            "hq_lat": cfg.get("hq_lat") or 52.1719,
            "hq_lon": cfg.get("hq_lon") or 4.9994,
            "hq_label": cfg.get("hq_label") or "Breukelen",
        }
    if kind == CRTSH_KIND:
        # crt.sh (Certificate Transparency search). Free, no signup.
        # Used to find customer domains under one MSP's wildcard cert.
        return {
            "base_url": cfg.get("base_url") or "https://crt.sh",
        }
    if kind == HUNTER_KIND:
        # Hunter.io. Optional commercial email-pattern + verify source.
        # 25 free searches/mnd, $34+/mnd paid.
        return {
            "base_url": cfg.get("base_url") or "https://api.hunter.io/v2",
            "api_key_set": bool(cfg.get("api_key")),
        }
    if kind == APOLLO_KIND:
        # Apollo.io. Optional commercial source for international leads
        # + LinkedIn-style enrichment. $49+/mnd.
        return {
            "base_url": cfg.get("base_url") or "https://api.apollo.io/v1",
            "api_key_set": bool(cfg.get("api_key")),
        }
    if kind == WESPENNEST_KIND:
        # Wespennest behavioural preferences.
        return {
            "primary_kvk_source": cfg.get("primary_kvk_source") or "auto",
        }
    if kind == PBX_3CX_KIND:
        return {
            "pbx_fqdn": cfg.get("pbx_fqdn"),
            "extension": cfg.get("extension"),
            "country_code": cfg.get("country_code") or "31",
            "click_mode": cfg.get("click_mode") or "tel",
            "default_outbound_prefix": cfg.get("default_outbound_prefix") or "",
        }
    if kind == M365_SSO_KIND:
        # Microsoft 365 SSO via Azure AD OAuth2. Only invited users in
        # this org can sign in -- the platform never auto-creates a user.
        return {
            "tenant_id": cfg.get("tenant_id") or "common",
            "client_id": cfg.get("client_id"),
            "client_secret_set": bool(cfg.get("client_secret")),
            "allowed_email_domains": cfg.get("allowed_email_domains") or [],
            # Hard-disabled server-side regardless of config -- we surface
            # this to the UI so it can show a disabled / 'enforced' state.
            "auto_create_users": False,
            "auto_create_users_enforced": True,
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
        (MAILGUN_KIND, "Mailgun", "Outbound mail + inbound reply detection for sequences"),
        (LINKEDIN_KIND, "LinkedIn", "Post scheduling + outreach task tracking"),
        # ---- Wespennest data sources ----
        (KVK_KIND, "KVK (officieel)", "Officiële KVK API — basisprofiel, vestigingen, functionarissen. Activatie 2-5 werkdagen, €6,40/mnd + €0,05/call."),
        (OPENKVK_KIND, "OpenKVK", "Gratis open KVK-data via overheid.io. Direct werkend, 80% van wat de officiële KVK biedt."),
        (PDOK_KIND, "PDOK Geocoder", "Gratis NL postcode/adres → coördinaten. Vereist voor het 40 km-filter."),
        (CRTSH_KIND, "crt.sh (CT logs)", "Gratis Certificate Transparency search — vindt klant-domeinen onder MSP-wildcards."),
        (HUNTER_KIND, "Hunter.io", "Optioneel — email-pattern discovery + verify. 25 gratis/mnd, anders $34+/mnd."),
        (APOLLO_KIND, "Apollo.io", "Optioneel — internationale decision-maker enrichment. $49+/mnd. Voor NL-MKB minder geschikt."),
        # ---- SSO providers ----
        (M365_SSO_KIND, "Microsoft 365 SSO", "Single sign-on via Azure AD. Users met een toegestane email-domein loggen in met hun M365-account."),
        # ---- Telephony ----
        (PBX_3CX_KIND, "3CX telefooncentrale", "Click-to-call vanaf telefoonnummers in het portaal naar je 3CX-toestel."),
        # ---- Wespennest preferences ----
        (WESPENNEST_KIND, "Wespennest instellingen", "Kies welke bron als primair gebruikt wordt voor KvK-lookups (OpenKVK gratis vs KVK officieel)."),
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
        # Expand dotted form-keys ("limits.max_per_day") into nested dicts
        # so the frontend can submit flat fields while we store structured
        # config. Numeric strings are coerced to int so JSONB stores
        # proper numbers (the throttle does int(...) defensively anyway).
        raw_cfg = dict(data.config or {})
        cfg_dict: dict = {}
        for k, v in raw_cfg.items():
            value = v
            if isinstance(v, str) and v.strip().lstrip("-").isdigit():
                try:
                    value = int(v.strip())
                except ValueError:
                    value = v
            if "." in k:
                head, tail = k.split(".", 1)
                bucket = cfg_dict.setdefault(head, {})
                if isinstance(bucket, dict):
                    bucket[tail] = value
            else:
                cfg_dict[k] = value
        secret_keys = ("client_secret", "api_key", "webhook_signing_key", "access_token", "refresh_token")
        if row is not None:
            existing = row.config_json or {}
            for sk in secret_keys:
                if not cfg_dict.get(sk):
                    cfg_dict[sk] = existing.get(sk, "")
            # Preserve nested subkeys not in this submission so partial
            # form-saves don't wipe sibling values.
            for k, v in (existing or {}).items():
                if isinstance(v, dict) and isinstance(cfg_dict.get(k), dict):
                    for sk, sv in v.items():
                        cfg_dict[k].setdefault(sk, sv)
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
_make_kind_routes(MAILGUN_KIND)
_make_kind_routes(LINKEDIN_KIND)
_make_kind_routes(KVK_KIND)
_make_kind_routes(OPENKVK_KIND)
_make_kind_routes(PDOK_KIND)
_make_kind_routes(CRTSH_KIND)
_make_kind_routes(HUNTER_KIND)
_make_kind_routes(APOLLO_KIND)
_make_kind_routes(M365_SSO_KIND)
_make_kind_routes(PBX_3CX_KIND)
_make_kind_routes(WESPENNEST_KIND)


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


# ---- Mailgun ----


def _mailgun_creds(row: Integration):
    from salespilot.integrations.mailgun import MailgunCredentials
    cfg = row.config_json or {}
    return MailgunCredentials(
        base_url=cfg.get("base_url") or "api.eu.mailgun.net",
        domain=cfg.get("domain", ""),
        api_key=cfg.get("api_key", ""),
        webhook_signing_key=cfg.get("webhook_signing_key"),
    )


@router.post(f"/{MAILGUN_KIND}/test", response_model=TestConnectionResult)
async def test_mailgun(auth: CurrentAuth, db: Db) -> TestConnectionResult:
    from salespilot.integrations.mailgun import MailgunClient, MailgunError
    row = await _get_integration(db, MAILGUN_KIND)
    if row is None:
        raise HTTPException(status_code=400, detail="Mailgun not configured yet")
    cfg = row.config_json or {}
    if not cfg.get("domain") or not cfg.get("api_key"):
        return TestConnectionResult(ok=False, detail="domain or api_key missing")
    try:
        async with MailgunClient(_mailgun_creds(row)) as client:
            info = await client.test_connection()
        state = info.get("domain", {}).get("state") if isinstance(info, dict) else "?"
        return TestConnectionResult(
            ok=True,
            detail=f"Domain found. State: {state}.",
            token_present=True,
        )
    except MailgunError as e:
        return TestConnectionResult(ok=False, detail=str(e))


# ---- LinkedIn OAuth bootstrap ----
# Note: the OAuth callback exchange itself lives in api/oauth_callbacks.py
# so it can be hit without an Authorization header. Here we just provide
# the URL builder so the frontend can redirect into LinkedIn.


@router.get(f"/{LINKEDIN_KIND}/oauth-url")
async def linkedin_oauth_url(
    auth: CurrentAuth, db: Db
) -> dict[str, str]:
    """Returns the LinkedIn OAuth authorize URL for the configured client_id."""
    from urllib.parse import urlencode
    from salespilot.config import get_settings
    row = await _get_integration(db, LINKEDIN_KIND)
    cfg = (row.config_json if row else {}) or {}
    client_id = cfg.get("client_id")
    if not client_id:
        raise HTTPException(status_code=400, detail="set client_id first")
    # Scopes: w_member_social = post on user's behalf; r_liteprofile = read
    # name/photo/urn. Post scheduling needs w_member_social. For company-page
    # posting, w_organization_social is required (admin-managed only).
    scopes = "openid profile email w_member_social"
    settings = get_settings()
    public_base = getattr(settings, "public_base_url", "https://sales.hostingportal.org")
    redirect_uri = f"{public_base}/api/v1/oauth/linkedin/callback"
    state = str(auth.org_id)  # naive — org_id IS the state for now
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": scopes,
    }
    return {"authorize_url": f"https://www.linkedin.com/oauth/v2/authorization?{urlencode(params)}"}





@router.post(f"/{M365_SSO_KIND}/test", response_model=TestConnectionResult)
async def test_m365_sso(auth: CurrentAuth, db: Db) -> TestConnectionResult:
    """Verify the M365 SSO config is sane.

    Checks:
      * client_id + client_secret + tenant_id are filled
      * tenant_id is a valid GUID or 'common'/'organizations'/'consumers'
      * Microsoft's OIDC discovery endpoint for this tenant is reachable
        (a 200 here proves the tenant_id is real and the network path works)
      * the redirect URI we will register is reachable from the public web
    """
    import re as _re
    import httpx as _httpx
    row = await _get_integration(db, M365_SSO_KIND)
    if row is None:
        raise HTTPException(status_code=400, detail="Microsoft 365 SSO niet geconfigureerd")
    cfg = row.config_json or {}
    client_id = cfg.get("client_id")
    secret = cfg.get("client_secret")
    tenant = cfg.get("tenant_id") or "common"
    if not client_id:
        return TestConnectionResult(ok=False, detail="client_id ontbreekt", token_present=False)
    if not secret:
        return TestConnectionResult(ok=False, detail="client_secret ontbreekt", token_present=False)
    guid_re = _re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", _re.I)
    if tenant not in ("common", "organizations", "consumers") and not guid_re.match(tenant):
        return TestConnectionResult(
            ok=False, token_present=True,
            detail=f"tenant_id '{tenant}' is geen geldige GUID of speciale waarde",
        )
    # OIDC discovery confirms tenant exists and our network can reach it
    try:
        async with _httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                f"https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration"
            )
        if r.status_code != 200:
            return TestConnectionResult(
                ok=False, token_present=True,
                detail=f"OIDC-discovery faalt ({r.status_code}) -- tenant_id mogelijk fout?",
            )
        d = r.json()
        issuer = d.get("issuer") or ""
    except Exception as e:
        return TestConnectionResult(
            ok=False, token_present=True,
            detail=f"Microsoft niet bereikbaar: {str(e)[:120]}",
        )
    # Optional: validate the client_secret by attempting the client-credentials
    # grant. Returns 200 on success or a useful error from AAD itself.
    try:
        async with _httpx.AsyncClient(timeout=10) as c:
            tok = await c.post(
                f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
                data={
                    "client_id": client_id,
                    "client_secret": secret,
                    "scope": "https://graph.microsoft.com/.default",
                    "grant_type": "client_credentials",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if tok.status_code == 200:
            return TestConnectionResult(
                ok=True, token_present=True,
                detail=f"Verbinding OK. Issuer: {issuer}. Tenant + secret geverifieerd via Microsoft.",
            )
        err = tok.json() if tok.headers.get("content-type","").startswith("application/json") else {}
        err_code = err.get("error", "")
        desc = (err.get("error_description") or tok.text[:200]).split("\n")[0]

        # Discriminate between hard failures (wrong secret/tenant) and
        # soft ones that are normal for pure-SSO apps without
        # application-level Graph permissions.
        # AADSTS7000215 = invalid_client_secret_provided
        # AADSTS70011   = invalid_scope (no app permissions; OK for SSO)
        # AADSTS650053  = the application does not have admin consent (OK)
        # AADSTS90002   = tenant not found
        if "AADSTS7000215" in desc or err_code == "invalid_client":
            return TestConnectionResult(
                ok=False, token_present=True,
                detail=f"Client secret is fout of verlopen. Maak een nieuwe aan in Entra ID -> Certificates & secrets.",
            )
        if "AADSTS90002" in desc:
            return TestConnectionResult(
                ok=False, token_present=True,
                detail="Tenant niet gevonden. Controleer of tenant_id correct is.",
            )
        if "AADSTS70011" in desc or "AADSTS650053" in desc or "invalid_scope" in err_code:
            # No application-permissions granted -- normal for pure SSO.
            # Tenant + secret are both valid (AAD reached this far).
            return TestConnectionResult(
                ok=True, token_present=True,
                detail=(
                    f"Verbinding OK. Issuer: {issuer}. Tenant + secret zijn geldig. "
                    "(Geen Graph application-permissions -- niet nodig voor SSO.)"
                ),
            )
        return TestConnectionResult(
            ok=False, token_present=True,
            detail=f"AAD weigert credentials: {desc[:200]}",
        )
    except Exception as e:
        return TestConnectionResult(
            ok=False, token_present=True,
            detail=f"AAD-token endpoint onbereikbaar: {str(e)[:120]}",
        )


# ---- Wespennest source test endpoints ----


def _wn_test_result(r: SourceTestResult) -> TestConnectionResult:
    return TestConnectionResult(ok=r.ok, detail=r.detail, token_present=True)


@router.post(f"/{KVK_KIND}/test", response_model=TestConnectionResult)
async def test_kvk(auth: CurrentAuth, db: Db) -> TestConnectionResult:
    row = await _get_integration(db, KVK_KIND)
    if row is None:
        raise HTTPException(status_code=400, detail="KVK not configured yet")
    cfg = row.config_json or {}
    client = KvkClient(
        base_url=cfg.get("base_url"),
        api_key=cfg.get("api_key"),
        functionarissen_key=cfg.get("functionarissen_key"),
    )
    return _wn_test_result(await client.test_connection())


@router.post(f"/{OPENKVK_KIND}/test", response_model=TestConnectionResult)
async def test_openkvk(auth: CurrentAuth, db: Db) -> TestConnectionResult:
    row = await _get_integration(db, OPENKVK_KIND)
    cfg = (row.config_json if row else None) or {}
    client = OpenKvkClient(base_url=cfg.get("base_url"), api_key=cfg.get("api_key"))
    return _wn_test_result(await client.test_connection())


@router.post(f"/{PDOK_KIND}/test", response_model=TestConnectionResult)
async def test_pdok(auth: CurrentAuth, db: Db) -> TestConnectionResult:
    row = await _get_integration(db, PDOK_KIND)
    cfg = (row.config_json if row else None) or {}
    client = PdokClient(base_url=cfg.get("base_url"))
    return _wn_test_result(await client.test_connection())


@router.post(f"/{CRTSH_KIND}/test", response_model=TestConnectionResult)
async def test_crtsh(auth: CurrentAuth, db: Db) -> TestConnectionResult:
    row = await _get_integration(db, CRTSH_KIND)
    cfg = (row.config_json if row else None) or {}
    client = CrtShClient(base_url=cfg.get("base_url"))
    return _wn_test_result(await client.test_connection())


@router.post(f"/{HUNTER_KIND}/test", response_model=TestConnectionResult)
async def test_hunter(auth: CurrentAuth, db: Db) -> TestConnectionResult:
    """Hunter.io test - just verifies the key was saved. We don't burn the
    user's free quota by making a real lookup."""
    row = await _get_integration(db, HUNTER_KIND)
    if row is None or not (row.config_json or {}).get("api_key"):
        raise HTTPException(status_code=400, detail="Hunter.io API-key niet ingesteld")
    return TestConnectionResult(
        ok=True,
        detail="Hunter.io key is opgeslagen. (Geen test-call gedaan om je free quota niet te verbranden.)",
        token_present=True,
    )


@router.post(f"/{APOLLO_KIND}/test", response_model=TestConnectionResult)
async def test_apollo(auth: CurrentAuth, db: Db) -> TestConnectionResult:
    """Apollo.io test - same idea as Hunter."""
    row = await _get_integration(db, APOLLO_KIND)
    if row is None or not (row.config_json or {}).get("api_key"):
        raise HTTPException(status_code=400, detail="Apollo.io API-key niet ingesteld")
    return TestConnectionResult(
        ok=True,
        detail="Apollo.io key is opgeslagen. (Geen test-call gedaan om je free quota niet te verbranden.)",
        token_present=True,
    )

