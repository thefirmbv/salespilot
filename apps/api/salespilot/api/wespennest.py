"""API endpoints for the Wespennest acquisition pipeline.

  GET  /wespennest/summary
  GET  /wespennest/msps
  POST /wespennest/msps
  PATCH /wespennest/msps/{id}
  DELETE /wespennest/msps/{id}
  GET  /wespennest/leads
  GET  /wespennest/leads/{kvk_company_id}
  POST /wespennest/leads/{kvk_company_id}/convert-to-prospect
  GET  /wespennest/acquisition-signals
  PATCH /wespennest/acquisition-signals/{id}
  GET  /wespennest/pipeline-status
  POST /wespennest/pipeline/{job_kind}/run
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select

from salespilot.deps import CurrentAuth, Db
from salespilot.integrations.wespennest_pipeline import JOB_KINDS, run_pipeline_job
from salespilot.models.crm import Company, CompanySource, Contact
from salespilot.models.wespennest import (
    WnAcquisitionSignal,
    WnDecisionMaker,
    WnDomain,
    WnDomainKvk,
    WnDomainSignals,
    WnKvkCompany,
    WnMsp,
    WnMspFingerprint,
    WnPipelineRun,
    WnVendorAttribution,
)
from salespilot.schemas.wespennest import (
    AcquisitionSignalPublic,
    AcquisitionSignalUpdate,
    LeadPublic,
    LeadsSummary,
    MspCreate,
    MspPublic,
    MspUpdate,
    PipelineRunPublic,
    PipelineStatusSummary,
    PipelineTriggerResult,
)


router = APIRouter(prefix="/wespennest", tags=["wespennest"])


# ----------------------------------------------------------------------
# Summary KPIs
# ----------------------------------------------------------------------


@router.get("/summary", response_model=LeadsSummary)
async def summary(auth: CurrentAuth, db: Db) -> LeadsSummary:
    """Roll-up across the whole pipeline for the dashboard."""
    msps_total = (
        await db.execute(select(func.count(WnMsp.id)).where(WnMsp.is_active == True))  # noqa: E712
    ).scalar() or 0
    msps_with_acq = (
        await db.execute(
            select(func.count(WnMsp.id))
            .where(WnMsp.is_active == True, WnMsp.acquired_date.is_not(None))  # noqa: E712
        )
    ).scalar() or 0
    domains_total = (await db.execute(select(func.count(WnDomain.id)))).scalar() or 0

    # Use the latest signals row per domain to count M365 hits.
    domains_with_m365 = (await db.execute(
        select(func.count(WnDomainSignals.id))
        .where(WnDomainSignals.m365["is_m365"].as_string() == "true")
    )).scalar() or 0

    kvk_total = (await db.execute(select(func.count(WnKvkCompany.id)))).scalar() or 0
    within_40km = (
        await db.execute(
            select(func.count(WnKvkCompany.id)).where(WnKvkCompany.km_to_hq <= 40)
        )
    ).scalar() or 0
    with_dm = (await db.execute(
        select(func.count(func.distinct(WnDecisionMaker.kvk_company_id)))
        .where(WnDecisionMaker.email.is_not(None))
    )).scalar() or 0

    avg_km_row = (await db.execute(select(func.avg(WnKvkCompany.km_to_hq)))).scalar()
    avg_km = float(avg_km_row) if avg_km_row is not None else 0.0

    return LeadsSummary(
        total_msps=msps_total,
        msps_with_acquisition=msps_with_acq,
        total_domains=domains_total,
        domains_with_m365=domains_with_m365,
        qualified_leads=kvk_total,
        qualified_with_decision_maker=with_dm,
        qualified_within_40km=within_40km,
        qualified_msps_with_recent_acquisition=msps_with_acq,
        avg_km_to_hq=round(avg_km, 1),
    )


# ----------------------------------------------------------------------
# MSPs
# ----------------------------------------------------------------------


async def _enrich_msp(db: Db, m: WnMsp) -> MspPublic:
    p = MspPublic.model_validate(m)
    # Domain count = via vendor_attribution for this MSP
    p.domain_count = (
        await db.execute(
            select(func.count(WnVendorAttribution.id))
            .where(WnVendorAttribution.msp_id == m.id)
        )
    ).scalar() or 0
    # Lead count = unique kvk companies behind those domains
    p.lead_count = (
        await db.execute(
            select(func.count(func.distinct(WnDomainKvk.kvk_company_id)))
            .join(WnVendorAttribution, WnVendorAttribution.domain_id == WnDomainKvk.domain_id)
            .where(WnVendorAttribution.msp_id == m.id)
        )
    ).scalar() or 0
    p.fingerprint_count = (
        await db.execute(
            select(func.count(WnMspFingerprint.id))
            .where(WnMspFingerprint.msp_id == m.id)
        )
    ).scalar() or 0
    return p


@router.get("/msps", response_model=list[MspPublic])
async def list_msps(
    auth: CurrentAuth,
    db: Db,
    include_inactive: bool = False,
) -> list[MspPublic]:
    stmt = select(WnMsp)
    if not include_inactive:
        stmt = stmt.where(WnMsp.is_active == True)  # noqa: E712
    stmt = stmt.order_by(desc(WnMsp.acquired_date).nullslast(), WnMsp.name.asc())
    rows = (await db.execute(stmt)).scalars().all()
    return [await _enrich_msp(db, m) for m in rows]


@router.post("/msps", response_model=MspPublic, status_code=201)
async def create_msp(data: MspCreate, auth: CurrentAuth, db: Db) -> MspPublic:
    now = datetime.now(UTC)
    m = WnMsp(
        id=uuid4(),
        org_id=auth.org_id,
        created_at=now,
        updated_at=now,
        is_active=True,
        **data.model_dump(),
    )
    db.add(m)
    await db.flush()
    return await _enrich_msp(db, m)


@router.patch("/msps/{msp_id}", response_model=MspPublic)
async def update_msp(
    msp_id: UUID, data: MspUpdate, auth: CurrentAuth, db: Db
) -> MspPublic:
    m = await db.get(WnMsp, msp_id)
    if m is None:
        raise HTTPException(status_code=404, detail="msp not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(m, k, v)
    await db.flush()
    return await _enrich_msp(db, m)


@router.delete("/msps/{msp_id}", status_code=204)
async def delete_msp(msp_id: UUID, auth: CurrentAuth, db: Db) -> None:
    m = await db.get(WnMsp, msp_id)
    if m is None:
        raise HTTPException(status_code=404, detail="msp not found")
    await db.delete(m)
    await db.flush()


# ----------------------------------------------------------------------
# Leads (qualified candidates for bell-list)
# ----------------------------------------------------------------------


@router.get("/leads", response_model=list[LeadPublic])
async def list_leads(
    auth: CurrentAuth,
    db: Db,
    msp_id: UUID | None = None,
    has_m365: bool | None = None,
    has_email: bool | None = None,
    max_km: float | None = Query(None, ge=0, le=500),
    min_fte: int | None = Query(None, ge=0),
    max_fte: int | None = Query(None, ge=0),
    limit: int = Query(200, le=500),
) -> list[LeadPublic]:
    """The bell-list. Joins KVK + (latest) M365 signal + MSP attribution
    + decision-maker. Filters narrow the result down."""
    # Build the latest-signals subquery: most recent WnDomainSignals row per domain.
    sub_latest = (
        select(
            WnDomainSignals.domain_id,
            func.max(WnDomainSignals.scanned_at).label("max_at"),
        )
        .group_by(WnDomainSignals.domain_id)
        .subquery()
    )

    stmt = (
        select(
            WnKvkCompany,
            WnDomain,
            WnDomainSignals,
            WnMsp,
            WnVendorAttribution,
            WnDecisionMaker,
        )
        .select_from(WnKvkCompany)
        .join(WnDomainKvk, WnDomainKvk.kvk_company_id == WnKvkCompany.id, isouter=True)
        .join(WnDomain, WnDomain.id == WnDomainKvk.domain_id, isouter=True)
        .join(sub_latest, sub_latest.c.domain_id == WnDomain.id, isouter=True)
        .join(
            WnDomainSignals,
            (WnDomainSignals.domain_id == WnDomain.id)
            & (WnDomainSignals.scanned_at == sub_latest.c.max_at),
            isouter=True,
        )
        .join(
            WnVendorAttribution,
            WnVendorAttribution.domain_id == WnDomain.id,
            isouter=True,
        )
        .join(WnMsp, WnMsp.id == WnVendorAttribution.msp_id, isouter=True)
        .join(
            WnDecisionMaker,
            WnDecisionMaker.kvk_company_id == WnKvkCompany.id,
            isouter=True,
        )
    )

    if msp_id is not None:
        stmt = stmt.where(WnMsp.id == msp_id)
    if max_km is not None:
        stmt = stmt.where(WnKvkCompany.km_to_hq <= max_km)
    if min_fte is not None:
        stmt = stmt.where(WnKvkCompany.werkzame_personen >= min_fte)
    if max_fte is not None:
        stmt = stmt.where(WnKvkCompany.werkzame_personen <= max_fte)
    if has_email is True:
        stmt = stmt.where(WnDecisionMaker.email.is_not(None))
    if has_email is False:
        stmt = stmt.where(WnDecisionMaker.email.is_(None))

    stmt = stmt.order_by(
        desc(WnMsp.acquired_date).nullslast(),
        WnKvkCompany.km_to_hq.asc().nullslast(),
    ).limit(limit)

    rows = (await db.execute(stmt)).all()

    # We may need to know if this kvk-company is already a SalesPilot Company
    # (i.e. converted to a prospect). Look up by kvk_nummer in companies.
    # Match WnKvkCompany.handelsnaam -> SalesPilot Company.name. We pull
    # candidate companies cheaply rather than building a complex predicate.
    name_keys = {
        (r[0].handelsnaam or r[0].kvk_nummer).strip().lower()
        for r in rows
    }
    existing: dict[str, Company] = {}
    if name_keys:
        for c in (await db.execute(select(Company))).scalars():
            key = (c.name or "").strip().lower()
            if key in name_keys:
                existing[key] = c

    out: list[LeadPublic] = []
    for kvk, dom, sig, msp, va, dm in rows:
        m365 = (sig.m365 if sig else {}) or {}
        # has_m365 filter happens after the m365 dict is reified
        has_m365_val: bool | None = None
        if m365:
            v = m365.get("is_m365")
            if isinstance(v, bool):
                has_m365_val = v
            elif isinstance(v, str):
                has_m365_val = v.lower() == "true"
        if has_m365 is not None and has_m365_val != has_m365:
            continue
        naam_parts = [dm.voornaam, dm.tussenvoegsel, dm.achternaam] if dm else []
        naam = " ".join(p for p in naam_parts if p).strip() or None
        existing_company = existing.get((kvk.handelsnaam or kvk.kvk_nummer).strip().lower())
        out.append(
            LeadPublic(
                kvk_company_id=kvk.id,
                kvk_nummer=kvk.kvk_nummer,
                handelsnaam=kvk.handelsnaam or kvk.kvk_nummer,
                rechtsvorm=kvk.rechtsvorm,
                werkzame_personen=kvk.werkzame_personen,
                plaats=kvk.plaats,
                postcode=kvk.postcode,
                km_to_hq=kvk.km_to_hq,
                telefoon_bedrijf=kvk.telefoon,
                domain_id=dom.id if dom else None,
                domain=dom.domain if dom else None,
                has_m365=has_m365_val,
                m365_tier_hint=m365.get("license_tier_hint") if isinstance(m365, dict) else None,
                msp_id=msp.id if msp else None,
                msp_name=msp.name if msp else None,
                msp_acquired_by=msp.acquired_by if msp else None,
                msp_acquired_date=msp.acquired_date if msp else None,
                msp_confidence=va.confidence if va else None,
                decision_maker_id=dm.id if dm else None,
                contact_naam=naam,
                contact_functie=dm.functie if dm else None,
                contact_email=dm.email if dm else None,
                contact_email_verified=dm.email_verified if dm else None,
                contact_telefoon=dm.telefoon if dm else None,
                existing_contact_id=existing_company.id if existing_company else None,
                in_sequence=False,  # filled when sequences are linked
            )
        )
    return out


@router.post("/leads/{kvk_company_id}/convert-to-prospect")
async def convert_to_prospect(
    kvk_company_id: UUID, auth: CurrentAuth, db: Db
) -> dict[str, Any]:
    """Turn a Wespennest lead into a regular SalesPilot Company (prospect)
    + Contact so the user can drop it into a sequence."""
    kvk = await db.get(WnKvkCompany, kvk_company_id)
    if kvk is None:
        raise HTTPException(status_code=404, detail="lead not found")

    # SalesPilot's Company model doesn't have a kvk_number field today, so
    # we fall back to a name + city match. When kvk_number lands on Company
    # in a future migration we can tighten this up.
    name_lc = (kvk.handelsnaam or kvk.kvk_nummer).strip().lower()
    candidates = (await db.execute(select(Company))).scalars().all()
    existing = next(
        (
            c for c in candidates
            if (c.name or "").strip().lower() == name_lc
            and (not kvk.plaats or (c.city or "").strip().lower() == kvk.plaats.strip().lower())
        ),
        None,
    )
    now = datetime.now(UTC)
    if existing is None:
        company = Company(
            id=uuid4(),
            org_id=auth.org_id,
            name=kvk.handelsnaam or kvk.kvk_nummer,
            source=CompanySource.SALESPILOT,
            city=kvk.plaats,
            employees=kvk.werkzame_personen,
            created_at=now,
            updated_at=now,
        )
        db.add(company)
        await db.flush()
    else:
        company = existing

    # Pull in decision-makers as Contacts (best-effort)
    dms = (
        await db.execute(
            select(WnDecisionMaker).where(WnDecisionMaker.kvk_company_id == kvk.id)
        )
    ).scalars().all()
    contacts_made = 0
    for dm in dms:
        if dm.contact_id:
            continue  # already converted
        if not dm.email and not dm.voornaam:
            continue
        c = Contact(
            id=uuid4(),
            org_id=auth.org_id,
            company_id=company.id,
            first_name=dm.voornaam,
            last_name=" ".join(p for p in [dm.tussenvoegsel, dm.achternaam] if p).strip() or None,
            email=dm.email,
            phone=dm.telefoon,
            job_title=dm.functie,
            created_at=now,
            updated_at=now,
        )
        db.add(c)
        await db.flush()
        dm.contact_id = c.id
        contacts_made += 1

    return {
        "ok": True,
        "company_id": str(company.id),
        "contacts_created": contacts_made,
    }


# ----------------------------------------------------------------------
# Acquisition feed
# ----------------------------------------------------------------------


async def _enrich_signal(db: Db, s: WnAcquisitionSignal) -> AcquisitionSignalPublic:
    p = AcquisitionSignalPublic.model_validate(s)
    if s.msp_id:
        m = await db.get(WnMsp, s.msp_id)
        if m:
            p.msp_name = m.name
    return p


@router.get("/acquisition-signals", response_model=list[AcquisitionSignalPublic])
async def list_signals(
    auth: CurrentAuth,
    db: Db,
    status: str | None = Query(None, description="comma-separated"),
    limit: int = Query(200, le=500),
) -> list[AcquisitionSignalPublic]:
    stmt = select(WnAcquisitionSignal)
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            stmt = stmt.where(WnAcquisitionSignal.status.in_(statuses))
    stmt = stmt.order_by(
        desc(WnAcquisitionSignal.published_at).nullslast(),
        desc(WnAcquisitionSignal.created_at),
    ).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [await _enrich_signal(db, s) for s in rows]


@router.patch("/acquisition-signals/{sig_id}", response_model=AcquisitionSignalPublic)
async def update_signal(
    sig_id: UUID, data: AcquisitionSignalUpdate, auth: CurrentAuth, db: Db
) -> AcquisitionSignalPublic:
    s = await db.get(WnAcquisitionSignal, sig_id)
    if s is None:
        raise HTTPException(status_code=404, detail="signal not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    if data.status in ("confirmed", "rejected"):
        s.reviewer_id = auth.user_id
        s.reviewed_at = datetime.now(UTC)
    await db.flush()
    return await _enrich_signal(db, s)


# ----------------------------------------------------------------------
# Pipeline status + triggers
# ----------------------------------------------------------------------


def _to_public(r: WnPipelineRun) -> PipelineRunPublic:
    p = PipelineRunPublic.model_validate(r)
    if r.finished_at and r.started_at:
        p.duration_seconds = round((r.finished_at - r.started_at).total_seconds(), 1)
    return p


@router.get("/pipeline-status", response_model=PipelineStatusSummary)
async def pipeline_status(auth: CurrentAuth, db: Db) -> PipelineStatusSummary:
    """For each known job_kind, return the latest run."""
    out: dict[str, PipelineRunPublic | None] = {k: None for k in JOB_KINDS}
    for kind in JOB_KINDS:
        row = (
            await db.execute(
                select(WnPipelineRun)
                .where(WnPipelineRun.job_kind == kind)
                .order_by(desc(WnPipelineRun.started_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is not None:
            out[kind] = _to_public(row)
    return PipelineStatusSummary(jobs=out)


@router.get("/pipeline-runs", response_model=list[PipelineRunPublic])
async def pipeline_runs(
    auth: CurrentAuth, db: Db, limit: int = Query(50, le=200)
) -> list[PipelineRunPublic]:
    rows = (
        await db.execute(
            select(WnPipelineRun)
            .order_by(desc(WnPipelineRun.started_at))
            .limit(limit)
        )
    ).scalars().all()
    return [_to_public(r) for r in rows]


@router.post("/pipeline/{job_kind}/run", response_model=PipelineTriggerResult)
async def trigger_pipeline_job(
    job_kind: str, auth: CurrentAuth, db: Db
) -> PipelineTriggerResult:
    if job_kind not in JOB_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown job_kind. Known: {', '.join(JOB_KINDS)}",
        )
    run = await run_pipeline_job(db, org_id=auth.org_id, job_kind=job_kind)
    return PipelineTriggerResult(
        ok=run.status == "success",
        detail=run.message or f"Job '{job_kind}' status: {run.status}",
        job_kind=job_kind,
        run_id=run.id,
    )


# ----------------------------------------------------------------------
# Customer discovery -- find end-customers of acquired MSPs via CT logs
# and DNS records. Per-MSP, opt-in methods, manual confirm/reject.
# ----------------------------------------------------------------------


class CustomerDiscoveryRequest(BaseModel):
    """POST /wespennest/msps/{msp_id}/discover-customers body."""
    methods: list[str] = Field(
        default_factory=lambda: ["crtsh_subdomains", "crtsh_san"],
        description="Subset of: crtsh_subdomains, crtsh_san, mx_lookup, "
                    "spf_include, reseller_substring",
    )
    candidate_domains: list[str] | None = Field(
        default=None,
        description="Required for DNS-based methods (mx/spf/reseller). "
                    "Pass a list of apex domains to test against.",
    )
    max_per_method: int = Field(default=100, ge=10, le=500)


class CustomerCandidatePublic(BaseModel):
    """One row returned by the discovery scanner."""
    domain: str
    method: str
    evidence: str
    confidence: int
    status: str = "candidate"  # candidate | saved | rejected
    existing_domain_id: UUID | None = None


class CustomerDiscoveryResult(BaseModel):
    ok: bool
    msp_id: UUID
    msp_name: str
    msp_apex: str | None = None
    methods_run: list[str]
    candidates: list[CustomerCandidatePublic]
    detail: str | None = None


@router.post(
    "/msps/{msp_id}/discover-customers",
    response_model=CustomerDiscoveryResult,
)
async def discover_customers_for_msp(
    msp_id: UUID, payload: CustomerDiscoveryRequest,
    auth: CurrentAuth, db: Db,
) -> CustomerDiscoveryResult:
    """Run customer-discovery methods against an MSP and return candidates.

    We deliberately DO NOT auto-save to wn_domains -- the user reviews
    the candidates first and explicitly saves the ones that look real
    via POST /msps/{msp_id}/save-customer-domains. This avoids polluting
    the leads pipeline with false positives.
    """
    from salespilot.integrations.customer_discovery import (
        _msp_apex, run_customer_discovery,
    )

    msp = await db.get(WnMsp, msp_id)
    if msp is None or msp.org_id != auth.org_id:
        raise HTTPException(status_code=404, detail="msp not found")

    apex = _msp_apex(msp.website, msp.name)
    if apex is None:
        return CustomerDiscoveryResult(
            ok=False, msp_id=msp_id, msp_name=msp.name,
            msp_apex=None, methods_run=[], candidates=[],
            detail="Geen apex-domein af te leiden uit naam of website",
        )

    candidates = await run_customer_discovery(
        msp_apex=apex,
        methods=payload.methods,
        candidate_domains=payload.candidate_domains,
        max_per_method=payload.max_per_method,
        # Context for AI-powered methods (website / press / linkedin)
        db=db, org_id=auth.org_id,
        msp_name=msp.name, msp_website=msp.website,
    )

    # Mark which candidates already live in wn_domains so the UI can
    # show 'al opgeslagen' badges
    existing_rows = (
        await db.execute(
            select(WnDomain).where(WnDomain.domain.in_([c.domain for c in candidates]))
        )
    ).scalars().all()
    existing_by_domain = {r.domain: r for r in existing_rows}

    out_candidates: list[CustomerCandidatePublic] = []
    for c in candidates:
        existing = existing_by_domain.get(c.domain)
        out_candidates.append(CustomerCandidatePublic(
            domain=c.domain, method=c.method, evidence=c.evidence,
            confidence=c.confidence,
            status="saved" if existing else "candidate",
            existing_domain_id=existing.id if existing else None,
        ))

    return CustomerDiscoveryResult(
        ok=True, msp_id=msp_id, msp_name=msp.name, msp_apex=apex,
        methods_run=payload.methods, candidates=out_candidates,
        detail=(
            f"{len(candidates)} kandidaten gevonden via "
            f"{', '.join(payload.methods)}"
        ),
    )


class SaveCustomerDomainsRequest(BaseModel):
    domains: list[str] = Field(min_length=1, max_length=500)
    discovery_method: str = Field(
        default="crtsh_subdomains",
        description="Annotated on the saved wn_domains row for traceability",
    )


@router.post("/msps/{msp_id}/save-customer-domains")
async def save_customer_domains(
    msp_id: UUID, payload: SaveCustomerDomainsRequest,
    auth: CurrentAuth, db: Db,
) -> dict[str, Any]:
    """Persist a subset of customer candidates into wn_domains.

    Idempotent: existing (org_id, domain) rows are kept. discovery_source
    is set to 'msp:<msp_id>:<method>' so we can later filter the leads
    page by 'customers of MSP X'.
    """
    msp = await db.get(WnMsp, msp_id)
    if msp is None or msp.org_id != auth.org_id:
        raise HTTPException(status_code=404, detail="msp not found")

    # discovery_source is varchar(40), so we keep the tag short:
    # 'msp:<first-8-hex>:<short-method>'. Full link is via the domain
    # appearing in this MSP's discover-customers result anyway.
    msp_short = str(msp_id)[:8]
    method_short = {
        "crtsh_subdomains": "crt-sub",
        "crtsh_san": "crt-san",
        "mx_lookup": "mx",
        "spf_include": "spf",
        "reseller_substring": "name",
    }.get(payload.discovery_method, payload.discovery_method[:10])
    source_tag = f"msp:{msp_short}:{method_short}"  # e.g. 'msp:00387f38:crt-sub' = 22 chars
    now = datetime.now(UTC)
    created = 0
    skipped = 0

    existing_rows = (
        await db.execute(
            select(WnDomain.domain).where(
                WnDomain.org_id == auth.org_id,
                WnDomain.domain.in_(payload.domains),
            )
        )
    ).scalars().all()
    existing_set = set(existing_rows)

    for d in payload.domains:
        d_clean = (d or "").strip().lower()
        if not d_clean or "." not in d_clean:
            continue
        if d_clean in existing_set:
            skipped += 1
            continue
        db.add(WnDomain(
            id=uuid4(), org_id=auth.org_id, domain=d_clean,
            discovery_source=source_tag, first_seen=now,
            status="pending", created_at=now, updated_at=now,
        ))
        created += 1
    await db.flush()
    return {
        "ok": True, "created": created, "skipped": skipped,
        "msp": msp.name, "source_tag": source_tag,
    }


# ----------------------------------------------------------------------
# Domain-level attributions endpoint
# Shows wn_domains with their vendor_attribution to MSPs. This is the
# 'pre-leads' pool -- domains we've identified as belonging to a specific
# MSP via DNS fingerprinting + customer-discovery, but haven't yet
# enriched with KVK/decision-maker data.
# ----------------------------------------------------------------------


class DomainAttribution(BaseModel):
    domain: str
    domain_id: UUID
    domain_status: str  # qualified_m365 | non_m365 | pending | scanned
    discovery_source: str | None
    first_seen: datetime
    last_scanned: datetime | None
    # Attribution(s): a domain can belong to multiple MSPs if signals fire on multiple
    attributions: list[dict[str, Any]] = Field(default_factory=list)


@router.get("/attributions", response_model=list[DomainAttribution])
async def list_domain_attributions(
    auth: CurrentAuth, db: Db,
    limit: int = Query(default=200, ge=1, le=2000),
    only_attributed: bool = Query(default=False),
    msp_id: UUID | None = Query(default=None),
) -> list[DomainAttribution]:
    """Return discovered domains with their MSP attributions.

    Each row joins WnDomain with WnVendorAttribution rows for the same
    domain. Used by the 'Toegekende klanten' view to show the bridge
    between customer-discovery (CT/website/LinkedIn) + DNS-fingerprint
    matching.
    """
    rows = (
        await db.execute(
            select(WnDomain).order_by(desc(WnDomain.first_seen)).limit(limit)
        )
    ).scalars().all()

    # Gather all attributions for these domains in one query
    domain_ids = [r.id for r in rows]
    attr_rows = []
    if domain_ids:
        q = select(WnVendorAttribution, WnMsp).join(
            WnMsp, WnMsp.id == WnVendorAttribution.msp_id,
        ).where(WnVendorAttribution.domain_id.in_(domain_ids))
        if msp_id:
            q = q.where(WnVendorAttribution.msp_id == msp_id)
        attr_rows = (await db.execute(q)).all()

    by_dom: dict[UUID, list[dict[str, Any]]] = {}
    for va, msp in attr_rows:
        by_dom.setdefault(va.domain_id, []).append({
            "msp_id": str(msp.id),
            "msp_name": msp.name,
            "msp_acquired_by": msp.acquired_by,
            "confidence": va.confidence,
            "rules_fired": list(va.rules_fired or []),
            "attributed_at": va.attributed_at.isoformat() if va.attributed_at else None,
        })

    out: list[DomainAttribution] = []
    for d in rows:
        attrs = by_dom.get(d.id, [])
        if only_attributed and not attrs:
            continue
        if msp_id and not attrs:
            continue
        out.append(DomainAttribution(
            domain=d.domain,
            domain_id=d.id,
            domain_status=d.status,
            discovery_source=d.discovery_source,
            first_seen=d.first_seen,
            last_scanned=d.last_scanned,
            attributions=sorted(attrs, key=lambda a: -a["confidence"]),
        ))
    return out
