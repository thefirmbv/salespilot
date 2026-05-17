"""API: Plesk + Openprovider monitoring endpoints.

Beide volgen het UniFi-pattern: dashboard, list, link-company,
sync-halopsa-assets, links-overview.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, select

from salespilot.deps import CurrentAuth, Db
from salespilot.models.crm import Company
from salespilot.models.hosting import (
    OpenproviderCompanyLink, OpenproviderDomain,
    PleskCompanyLink, PleskDomain, PleskStateEvent, PleskSubscription,
)


# ======================================================================
# /plesk
# ======================================================================

plesk_router = APIRouter(prefix="/plesk", tags=["plesk"])


# ----- Dashboard -----

class PleskDashboard(BaseModel):
    subscriptions_total: int
    subscriptions_active: int
    subscriptions_suspended: int
    subscriptions_disabled: int
    linked_count: int
    unlinked_count: int
    halopsa_synced_count: int
    last_polled: datetime | None
    state_events_24h: int


@plesk_router.get("/dashboard", response_model=PleskDashboard)
async def plesk_dashboard(auth: CurrentAuth, db: Db) -> PleskDashboard:
    total = (await db.execute(select(func.count(PleskSubscription.id)))).scalar() or 0
    active = (await db.execute(
        select(func.count(PleskSubscription.id)).where(PleskSubscription.status == "active")
    )).scalar() or 0
    suspended = (await db.execute(
        select(func.count(PleskSubscription.id)).where(PleskSubscription.status == "suspended")
    )).scalar() or 0
    disabled = (await db.execute(
        select(func.count(PleskSubscription.id)).where(PleskSubscription.status == "disabled")
    )).scalar() or 0
    linked_count = (await db.execute(select(func.count(PleskCompanyLink.id)))).scalar() or 0
    synced_count = (await db.execute(
        select(func.count(PleskSubscription.id)).where(
            PleskSubscription.halopsa_asset_id.is_not(None),
        )
    )).scalar() or 0
    last_polled = (
        await db.execute(select(func.max(PleskSubscription.last_polled)))
    ).scalar()
    state_events_24h = (await db.execute(
        select(func.count(PleskStateEvent.id)).where(
            PleskStateEvent.occurred_at >= datetime.now(UTC) - timedelta(hours=24),
        )
    )).scalar() or 0
    return PleskDashboard(
        subscriptions_total=total,
        subscriptions_active=active,
        subscriptions_suspended=suspended,
        subscriptions_disabled=disabled,
        linked_count=linked_count,
        unlinked_count=max(0, total - linked_count),
        halopsa_synced_count=synced_count,
        last_polled=last_polled,
        state_events_24h=state_events_24h,
    )


# ----- Subscriptions list -----

class PleskSubscriptionRow(BaseModel):
    id: UUID
    plesk_id: str
    name: str
    main_domain: str | None
    plan_name: str | None
    status: str
    owner_email: str | None
    disk_used_mb: int
    mailboxes_count: int
    company_id: UUID | None
    company_name: str | None
    halopsa_asset_id: int | None
    halopsa_synced_at: datetime | None
    last_polled: datetime | None


@plesk_router.get("/subscriptions", response_model=list[PleskSubscriptionRow])
async def list_subscriptions(
    auth: CurrentAuth, db: Db,
    status: str | None = Query(default=None),
    linked: bool | None = Query(default=None),
) -> list[PleskSubscriptionRow]:
    subs = (await db.execute(
        select(PleskSubscription).order_by(PleskSubscription.name)
    )).scalars().all()
    links = {
        l.subscription_id: l
        for l in (await db.execute(select(PleskCompanyLink))).scalars()
    }
    comp_ids = {l.company_id for l in links.values()}
    companies: dict[UUID, Company] = {}
    if comp_ids:
        companies = {
            c.id: c
            for c in (await db.execute(
                select(Company).where(Company.id.in_(comp_ids))
            )).scalars()
        }
    out: list[PleskSubscriptionRow] = []
    for s in subs:
        if status and s.status != status:
            continue
        link = links.get(s.id)
        if linked is True and link is None:
            continue
        if linked is False and link is not None:
            continue
        comp = companies.get(link.company_id) if link else None
        out.append(PleskSubscriptionRow(
            id=s.id, plesk_id=s.plesk_id, name=s.name,
            main_domain=s.main_domain, plan_name=s.plan_name,
            status=s.status, owner_email=s.owner_email,
            disk_used_mb=s.disk_used_mb,
            mailboxes_count=s.mailboxes_count,
            company_id=link.company_id if link else None,
            company_name=comp.name if comp else None,
            halopsa_asset_id=s.halopsa_asset_id,
            halopsa_synced_at=s.halopsa_synced_at,
            last_polled=s.last_polled,
        ))
    return out


# ----- Links overview (company -> subs) -----

class SubStub(BaseModel):
    subscription_id: UUID
    name: str
    main_domain: str | None
    plan_name: str | None
    status: str
    halopsa_asset_id: int | None


class PleskCompanyLinkSummary(BaseModel):
    company_id: UUID
    company_name: str
    halopsa_id: int | None
    subscriptions: list[SubStub]
    subscriptions_count: int
    synced_count: int


@plesk_router.get("/links", response_model=list[PleskCompanyLinkSummary])
async def list_links(auth: CurrentAuth, db: Db) -> list[PleskCompanyLinkSummary]:
    rows = (await db.execute(
        select(PleskCompanyLink, PleskSubscription, Company)
        .join(PleskSubscription, PleskSubscription.id == PleskCompanyLink.subscription_id)
        .join(Company, Company.id == PleskCompanyLink.company_id)
        .order_by(Company.name, PleskSubscription.name)
    )).all()
    by_company: dict[UUID, PleskCompanyLinkSummary] = {}
    for _link, sub, company in rows:
        s = by_company.get(company.id)
        if s is None:
            s = PleskCompanyLinkSummary(
                company_id=company.id, company_name=company.name,
                halopsa_id=getattr(company, "halopsa_id", None),
                subscriptions=[], subscriptions_count=0, synced_count=0,
            )
            by_company[company.id] = s
        s.subscriptions.append(SubStub(
            subscription_id=sub.id, name=sub.name,
            main_domain=sub.main_domain, plan_name=sub.plan_name,
            status=sub.status, halopsa_asset_id=sub.halopsa_asset_id,
        ))
        s.subscriptions_count += 1
        if sub.halopsa_asset_id:
            s.synced_count += 1
    return list(by_company.values())


# ----- Link / unlink -----

class LinkBody(BaseModel):
    company_id: UUID
    notes: str | None = None


@plesk_router.post("/subscriptions/{sub_id}/link-company")
async def link_subscription(
    sub_id: UUID, body: LinkBody, auth: CurrentAuth, db: Db,
) -> dict[str, Any]:
    sub = (await db.execute(
        select(PleskSubscription).where(PleskSubscription.id == sub_id)
    )).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription niet gevonden")
    company = (await db.execute(
        select(Company).where(Company.id == body.company_id)
    )).scalar_one_or_none()
    if company is None:
        raise HTTPException(status_code=404, detail="Company niet gevonden")
    existing = (await db.execute(
        select(PleskCompanyLink).where(PleskCompanyLink.subscription_id == sub_id)
    )).scalar_one_or_none()
    if existing:
        existing.company_id = body.company_id
        existing.notes = body.notes
    else:
        db.add(PleskCompanyLink(
            id=uuid4(), org_id=auth.org_id,
            subscription_id=sub_id, company_id=body.company_id,
            notes=body.notes,
        ))
    await db.flush()
    return {"ok": True, "subscription_name": sub.name, "company_name": company.name}


@plesk_router.delete("/subscriptions/{sub_id}/link-company")
async def unlink_subscription(
    sub_id: UUID, auth: CurrentAuth, db: Db,
) -> dict[str, Any]:
    existing = (await db.execute(
        select(PleskCompanyLink).where(PleskCompanyLink.subscription_id == sub_id)
    )).scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.flush()
    return {"ok": True}


# ======================================================================
# /openprovider
# ======================================================================

op_router = APIRouter(prefix="/openprovider", tags=["openprovider"])


class OpenproviderDashboard(BaseModel):
    domains_total: int
    domains_active: int
    expiring_30d: int
    expiring_90d: int
    linked_count: int
    unlinked_count: int
    halopsa_synced_count: int
    last_polled: datetime | None


@op_router.get("/dashboard", response_model=OpenproviderDashboard)
async def op_dashboard(auth: CurrentAuth, db: Db) -> OpenproviderDashboard:
    total = (await db.execute(select(func.count(OpenproviderDomain.id)))).scalar() or 0
    active = (await db.execute(
        select(func.count(OpenproviderDomain.id)).where(OpenproviderDomain.status == "active")
    )).scalar() or 0
    now = datetime.now(UTC)
    exp_30 = (await db.execute(
        select(func.count(OpenproviderDomain.id)).where(
            OpenproviderDomain.expires_at <= now + timedelta(days=30),
            OpenproviderDomain.expires_at >= now,
        )
    )).scalar() or 0
    exp_90 = (await db.execute(
        select(func.count(OpenproviderDomain.id)).where(
            OpenproviderDomain.expires_at <= now + timedelta(days=90),
            OpenproviderDomain.expires_at >= now,
        )
    )).scalar() or 0
    linked = (await db.execute(select(func.count(OpenproviderCompanyLink.id)))).scalar() or 0
    synced = (await db.execute(
        select(func.count(OpenproviderDomain.id)).where(
            OpenproviderDomain.halopsa_asset_id.is_not(None),
        )
    )).scalar() or 0
    last_polled = (
        await db.execute(select(func.max(OpenproviderDomain.last_polled)))
    ).scalar()
    return OpenproviderDashboard(
        domains_total=total, domains_active=active,
        expiring_30d=exp_30, expiring_90d=exp_90,
        linked_count=linked, unlinked_count=max(0, total - linked),
        halopsa_synced_count=synced,
        last_polled=last_polled,
    )


class OpenproviderDomainRow(BaseModel):
    id: UUID
    op_id: str
    name: str
    status: str
    auto_renew: bool
    registered_at: datetime | None
    expires_at: datetime | None
    nameservers: list[str]
    company_id: UUID | None
    company_name: str | None
    halopsa_asset_id: int | None
    halopsa_synced_at: datetime | None


@op_router.get("/domains", response_model=list[OpenproviderDomainRow])
async def list_op_domains(
    auth: CurrentAuth, db: Db,
    status: str | None = Query(default=None),
    linked: bool | None = Query(default=None),
    expiring_days: int | None = Query(default=None, ge=1, le=365),
) -> list[OpenproviderDomainRow]:
    q = select(OpenproviderDomain).order_by(OpenproviderDomain.name)
    if status:
        q = q.where(OpenproviderDomain.status == status)
    if expiring_days:
        now = datetime.now(UTC)
        q = q.where(
            OpenproviderDomain.expires_at >= now,
            OpenproviderDomain.expires_at <= now + timedelta(days=expiring_days),
        )
    domains = (await db.execute(q)).scalars().all()
    links = {
        l.domain_id: l
        for l in (await db.execute(select(OpenproviderCompanyLink))).scalars()
    }
    comp_ids = {l.company_id for l in links.values()}
    companies: dict[UUID, Company] = {}
    if comp_ids:
        companies = {
            c.id: c
            for c in (await db.execute(select(Company).where(Company.id.in_(comp_ids)))).scalars()
        }
    out: list[OpenproviderDomainRow] = []
    for d in domains:
        link = links.get(d.id)
        if linked is True and link is None:
            continue
        if linked is False and link is not None:
            continue
        comp = companies.get(link.company_id) if link else None
        out.append(OpenproviderDomainRow(
            id=d.id, op_id=d.op_id, name=d.name,
            status=d.status, auto_renew=d.auto_renew,
            registered_at=d.registered_at, expires_at=d.expires_at,
            nameservers=d.nameservers or [],
            company_id=link.company_id if link else None,
            company_name=comp.name if comp else None,
            halopsa_asset_id=d.halopsa_asset_id,
            halopsa_synced_at=d.halopsa_synced_at,
        ))
    return out


class OPCompanyLinkSummary(BaseModel):
    company_id: UUID
    company_name: str
    halopsa_id: int | None
    domains: list[dict[str, Any]]
    domains_count: int
    synced_count: int


@op_router.get("/links", response_model=list[OPCompanyLinkSummary])
async def list_op_links(auth: CurrentAuth, db: Db) -> list[OPCompanyLinkSummary]:
    rows = (await db.execute(
        select(OpenproviderCompanyLink, OpenproviderDomain, Company)
        .join(OpenproviderDomain, OpenproviderDomain.id == OpenproviderCompanyLink.domain_id)
        .join(Company, Company.id == OpenproviderCompanyLink.company_id)
        .order_by(Company.name, OpenproviderDomain.name)
    )).all()
    by_company: dict[UUID, OPCompanyLinkSummary] = {}
    for _link, dom, company in rows:
        s = by_company.get(company.id)
        if s is None:
            s = OPCompanyLinkSummary(
                company_id=company.id, company_name=company.name,
                halopsa_id=getattr(company, "halopsa_id", None),
                domains=[], domains_count=0, synced_count=0,
            )
            by_company[company.id] = s
        s.domains.append({
            "domain_id": str(dom.id),
            "name": dom.name,
            "expires_at": dom.expires_at.isoformat() if dom.expires_at else None,
            "halopsa_asset_id": dom.halopsa_asset_id,
        })
        s.domains_count += 1
        if dom.halopsa_asset_id:
            s.synced_count += 1
    return list(by_company.values())


@op_router.post("/domains/{domain_id}/link-company")
async def link_op_domain(
    domain_id: UUID, body: LinkBody, auth: CurrentAuth, db: Db,
) -> dict[str, Any]:
    dom = (await db.execute(
        select(OpenproviderDomain).where(OpenproviderDomain.id == domain_id)
    )).scalar_one_or_none()
    if dom is None:
        raise HTTPException(status_code=404, detail="Domein niet gevonden")
    company = (await db.execute(
        select(Company).where(Company.id == body.company_id)
    )).scalar_one_or_none()
    if company is None:
        raise HTTPException(status_code=404, detail="Company niet gevonden")
    existing = (await db.execute(
        select(OpenproviderCompanyLink).where(OpenproviderCompanyLink.domain_id == domain_id)
    )).scalar_one_or_none()
    if existing:
        existing.company_id = body.company_id
        existing.notes = body.notes
    else:
        db.add(OpenproviderCompanyLink(
            id=uuid4(), org_id=auth.org_id,
            domain_id=domain_id, company_id=body.company_id,
            notes=body.notes,
        ))
    await db.flush()
    return {"ok": True, "domain": dom.name, "company_name": company.name}


@op_router.delete("/domains/{domain_id}/link-company")
async def unlink_op_domain(
    domain_id: UUID, auth: CurrentAuth, db: Db,
) -> dict[str, Any]:
    existing = (await db.execute(
        select(OpenproviderCompanyLink).where(OpenproviderCompanyLink.domain_id == domain_id)
    )).scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.flush()
    return {"ok": True}


# ======================================================================
# Handmatige creatie (zonder API te hebben)
# ======================================================================
# Jasper wil langzaam migreren -- handmatig en met AI hulp. Onderstaande
# endpoints maken het mogelijk om rows in de tabellen te zetten zonder
# een live Plesk/Openprovider connectie te hebben. Zelfde tabellen.


class ManualPleskSubscriptionBody(BaseModel):
    name: str
    main_domain: str | None = None
    plan_name: str | None = None
    owner_email: str | None = None
    company_id: UUID | None = None
    notes: str | None = None


@plesk_router.post("/subscriptions/manual", response_model=PleskSubscriptionRow)
async def create_plesk_subscription_manual(
    body: ManualPleskSubscriptionBody, auth: CurrentAuth, db: Db,
) -> PleskSubscriptionRow:
    """Voeg een Plesk subscription handmatig toe. plesk_id krijgt
    prefix 'manual:' zodat hij bij een echte sync niet collidet met
    Plesk's eigen IDs."""
    # Genereer een ID dat niet kan botsen met Plesk's int-ids
    from uuid import uuid4 as _uuid4
    plesk_id = f"manual:{_uuid4()}"
    sub = PleskSubscription(
        id=_uuid4(), org_id=auth.org_id, plesk_id=plesk_id,
        name=body.name, main_domain=body.main_domain,
        plan_name=body.plan_name, owner_email=body.owner_email,
        status="active", is_enabled=True,
        raw={"source": "manual", "notes": body.notes or ""},
    )
    db.add(sub)
    await db.flush()

    if body.company_id:
        db.add(PleskCompanyLink(
            id=_uuid4(), org_id=auth.org_id,
            subscription_id=sub.id, company_id=body.company_id,
        ))
        await db.flush()

    company_name = None
    if body.company_id:
        c = (await db.execute(
            select(Company).where(Company.id == body.company_id)
        )).scalar_one_or_none()
        company_name = c.name if c else None

    return PleskSubscriptionRow(
        id=sub.id, plesk_id=sub.plesk_id, name=sub.name,
        main_domain=sub.main_domain, plan_name=sub.plan_name,
        status=sub.status, owner_email=sub.owner_email,
        disk_used_mb=0, mailboxes_count=0,
        company_id=body.company_id,
        company_name=company_name,
        halopsa_asset_id=None, halopsa_synced_at=None,
        last_polled=None,
    )


@plesk_router.delete("/subscriptions/{sub_id}")
async def delete_plesk_subscription(
    sub_id: UUID, auth: CurrentAuth, db: Db,
) -> dict[str, Any]:
    """Verwijder handmatig toegevoegde subscription. Live-gepolde subs
    (zonder 'manual:' prefix) zouden via Plesk weg moeten -- die
    blokkeren we hier expliciet om dataverlies te voorkomen."""
    sub = (await db.execute(
        select(PleskSubscription).where(PleskSubscription.id == sub_id)
    )).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Niet gevonden")
    if not sub.plesk_id.startswith("manual:"):
        raise HTTPException(
            status_code=400,
            detail="Deze subscription komt uit live Plesk-sync. Verwijder hem in Plesk; dan verdwijnt hij hier vanzelf na de volgende poll.",
        )
    await db.delete(sub)
    await db.flush()
    return {"ok": True}


class ManualOpDomainBody(BaseModel):
    name: str
    extension: str | None = None
    expires_at: datetime | None = None
    registered_at: datetime | None = None
    auto_renew: bool = True
    company_id: UUID | None = None
    notes: str | None = None


@op_router.post("/domains/manual", response_model=OpenproviderDomainRow)
async def create_op_domain_manual(
    body: ManualOpDomainBody, auth: CurrentAuth, db: Db,
) -> OpenproviderDomainRow:
    from uuid import uuid4 as _uuid4
    op_id = f"manual:{_uuid4()}"
    # Auto-detect extension from name if not given
    name = body.name.strip().lower()
    ext = body.extension
    if not ext and "." in name:
        ext = name.split(".", 1)[1]
    dom = OpenproviderDomain(
        id=_uuid4(), org_id=auth.org_id, op_id=op_id,
        name=name, extension=ext, status="active",
        auto_renew=body.auto_renew,
        registered_at=body.registered_at,
        expires_at=body.expires_at,
        nameservers=[], raw={"source": "manual", "notes": body.notes or ""},
    )
    db.add(dom)
    await db.flush()

    if body.company_id:
        db.add(OpenproviderCompanyLink(
            id=_uuid4(), org_id=auth.org_id,
            domain_id=dom.id, company_id=body.company_id,
        ))
        await db.flush()

    company_name = None
    if body.company_id:
        c = (await db.execute(
            select(Company).where(Company.id == body.company_id)
        )).scalar_one_or_none()
        company_name = c.name if c else None

    return OpenproviderDomainRow(
        id=dom.id, op_id=dom.op_id, name=dom.name,
        status=dom.status, auto_renew=dom.auto_renew,
        registered_at=dom.registered_at, expires_at=dom.expires_at,
        nameservers=[],
        company_id=body.company_id, company_name=company_name,
        halopsa_asset_id=None, halopsa_synced_at=None,
    )


@op_router.delete("/domains/{domain_id}")
async def delete_op_domain(
    domain_id: UUID, auth: CurrentAuth, db: Db,
) -> dict[str, Any]:
    dom = (await db.execute(
        select(OpenproviderDomain).where(OpenproviderDomain.id == domain_id)
    )).scalar_one_or_none()
    if dom is None:
        raise HTTPException(status_code=404, detail="Niet gevonden")
    if not dom.op_id.startswith("manual:"):
        raise HTTPException(
            status_code=400,
            detail="Komt uit live Openprovider-sync. Verwijder hem daar.",
        )
    await db.delete(dom)
    await db.flush()
    return {"ok": True}


# ======================================================================
# Plesk servers (multi-server beheer)
# ======================================================================
# Jasper draait 4-5 Plesk-servers. Elke server heeft eigen URL + API
# key. Subscriptions worden gekoppeld aan een server bij polling.

from salespilot.access import require_groups
from salespilot.models.hosting import PleskServer


class PleskServerRow(BaseModel):
    id: UUID
    name: str
    base_url: str
    verify_tls: bool
    is_enabled: bool
    has_api_key: bool
    last_sync_at: datetime | None
    last_sync_status: str | None
    last_sync_message: str | None
    notes: str | None
    subscriptions_count: int


@plesk_router.get("/servers", response_model=list[PleskServerRow])
async def list_plesk_servers(auth: CurrentAuth, db: Db) -> list[PleskServerRow]:
    servers = (await db.execute(
        select(PleskServer).order_by(PleskServer.name)
    )).scalars().all()
    # Counts per server
    counts = dict((await db.execute(
        select(PleskSubscription.server_id, func.count(PleskSubscription.id))
        .group_by(PleskSubscription.server_id)
    )).all())
    return [
        PleskServerRow(
            id=s.id, name=s.name, base_url=s.base_url,
            verify_tls=s.verify_tls, is_enabled=s.is_enabled,
            has_api_key=bool(s.api_key),
            last_sync_at=s.last_sync_at,
            last_sync_status=s.last_sync_status,
            last_sync_message=s.last_sync_message,
            notes=s.notes,
            subscriptions_count=int(counts.get(s.id, 0) or 0),
        )
        for s in servers
    ]


class CreateServerBody(BaseModel):
    name: str
    base_url: str
    api_key: str
    verify_tls: bool = True
    is_enabled: bool = True
    notes: str | None = None


@plesk_router.post("/servers", response_model=PleskServerRow)
async def create_plesk_server(
    body: CreateServerBody, auth: CurrentAuth, db: Db,
) -> PleskServerRow:
    require_groups("administrators")(auth)
    # Unique name binnen org
    existing = (await db.execute(
        select(PleskServer).where(PleskServer.name == body.name)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail=f"Server '{body.name}' bestaat al.")
    s = PleskServer(
        id=uuid4(), org_id=auth.org_id,
        name=body.name, base_url=body.base_url, api_key=body.api_key,
        verify_tls=body.verify_tls, is_enabled=body.is_enabled,
        notes=body.notes,
    )
    db.add(s)
    await db.flush()
    return PleskServerRow(
        id=s.id, name=s.name, base_url=s.base_url,
        verify_tls=s.verify_tls, is_enabled=s.is_enabled,
        has_api_key=bool(s.api_key),
        last_sync_at=None, last_sync_status=None, last_sync_message=None,
        notes=s.notes, subscriptions_count=0,
    )


class UpdateServerBody(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    verify_tls: bool | None = None
    is_enabled: bool | None = None
    notes: str | None = None


@plesk_router.put("/servers/{server_id}", response_model=PleskServerRow)
async def update_plesk_server(
    server_id: UUID, body: UpdateServerBody, auth: CurrentAuth, db: Db,
) -> PleskServerRow:
    require_groups("administrators")(auth)
    s = (await db.execute(
        select(PleskServer).where(PleskServer.id == server_id)
    )).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="Server niet gevonden")
    if body.name is not None: s.name = body.name
    if body.base_url is not None: s.base_url = body.base_url
    if body.api_key:  # leeg = behoud bestaande
        s.api_key = body.api_key
    if body.verify_tls is not None: s.verify_tls = body.verify_tls
    if body.is_enabled is not None: s.is_enabled = body.is_enabled
    if body.notes is not None: s.notes = body.notes
    await db.flush()
    count = (await db.execute(
        select(func.count(PleskSubscription.id))
        .where(PleskSubscription.server_id == s.id)
    )).scalar() or 0
    return PleskServerRow(
        id=s.id, name=s.name, base_url=s.base_url,
        verify_tls=s.verify_tls, is_enabled=s.is_enabled,
        has_api_key=bool(s.api_key),
        last_sync_at=s.last_sync_at,
        last_sync_status=s.last_sync_status,
        last_sync_message=s.last_sync_message,
        notes=s.notes, subscriptions_count=int(count),
    )


@plesk_router.delete("/servers/{server_id}")
async def delete_plesk_server(
    server_id: UUID, auth: CurrentAuth, db: Db,
) -> dict[str, Any]:
    require_groups("administrators")(auth)
    s = (await db.execute(
        select(PleskServer).where(PleskServer.id == server_id)
    )).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="Server niet gevonden")
    count = (await db.execute(
        select(func.count(PleskSubscription.id))
        .where(PleskSubscription.server_id == s.id)
    )).scalar() or 0
    if count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Kan server niet verwijderen: er zijn nog {count} subscriptions aan gekoppeld. Verwijder eerst de subscriptions of zet ze over naar een andere server.",
        )
    await db.delete(s)
    await db.flush()
    return {"ok": True}


@plesk_router.post("/servers/{server_id}/test")
async def test_plesk_server(
    server_id: UUID, auth: CurrentAuth, db: Db,
) -> dict[str, Any]:
    require_groups("administrators")(auth)
    from salespilot.integrations.plesk import (
        PleskClient, PleskCredentials, PleskError,
    )
    s = (await db.execute(
        select(PleskServer).where(PleskServer.id == server_id)
    )).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="Server niet gevonden")
    creds = PleskCredentials(
        api_key=s.api_key, base_url=s.base_url, verify_tls=s.verify_tls,
    )
    try:
        async with PleskClient(creds) as c:
            r = await c.test_connection()
        return {
            "ok": True,
            "detail": f"Plesk {r['version']} op {r['hostname']}. {r['clients_count']} klanten, {r['subscriptions_count']} subscriptions.",
        }
    except PleskError as e:
        return {"ok": False, "detail": str(e)}


# ======================================================================
# Openprovider WRITE endpoints (kost geld -- admin only + audit-log)
# ======================================================================

from salespilot.models.hosting import OpenproviderAuditLog


async def _op_client_from_db(db) -> "OpenproviderClient":
    """Bouw een Openprovider client uit de integratie-row."""
    from salespilot.models.integrations import Integration
    from salespilot.integrations.openprovider import (
        OpenproviderClient, OpenproviderCredentials,
    )
    row = (await db.execute(
        select(Integration).where(Integration.kind == "openprovider")
    )).scalar_one_or_none()
    if row is None or not row.is_enabled:
        raise HTTPException(status_code=400, detail="Openprovider niet ingesteld.")
    cfg = row.config_json or {}
    if not cfg.get("username") or not cfg.get("password"):
        raise HTTPException(status_code=400, detail="Credentials ontbreken.")
    creds = OpenproviderCredentials(
        username=cfg["username"], password=cfg["password"],
        base_url=cfg.get("base_url") or "https://api.openprovider.eu",
        bound_ip=cfg.get("bound_ip"),
    )
    return OpenproviderClient(creds)


async def _audit(
    db, *, org_id: UUID, user_id: UUID, action: str,
    domain_name: str | None = None, domain_id: UUID | None = None,
    request_payload: dict | None = None, response_payload: dict | None = None,
    status: str = "ok", error_message: str | None = None,
) -> None:
    from datetime import datetime as _dt, timezone as _tz
    db.add(OpenproviderAuditLog(
        id=uuid4(), org_id=org_id, user_id=user_id,
        action=action, domain_name=domain_name, domain_id=domain_id,
        request_payload=request_payload or {},
        response_payload=response_payload or {},
        status=status, error_message=error_message,
        occurred_at=_dt.now(_tz.utc),
    ))
    await db.flush()


# ----- Availability check (read, no money, no audit) -----

class CheckBody(BaseModel):
    name: str
    extension: str


@op_router.post("/domains/check")
async def check_domain_availability(
    body: CheckBody, auth: CurrentAuth, db: Db,
) -> dict[str, Any]:
    """Check if a domain is available + price for premium domains.
    No registration happens here."""
    from salespilot.integrations.openprovider import OpenproviderError
    require_groups("administrators")(auth)
    client = await _op_client_from_db(db)
    try:
        async with client as c:
            r = await c.check_availability(body.name, body.extension)
    except OpenproviderError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return r


# ----- Domain registration (MONEY -- admin + audit) -----

class RegisterBody(BaseModel):
    name: str
    extension: str
    period: int = 1
    owner_handle: str | None = None
    admin_handle: str | None = None
    tech_handle: str | None = None
    billing_handle: str | None = None
    name_servers: list[str] | None = None
    auto_renew: bool = True
    confirm_premium: bool = False
    company_id: UUID | None = None
    notes: str | None = None


@op_router.post("/domains/register")
async def register_domain(
    body: RegisterBody, auth: CurrentAuth, db: Db,
) -> dict[str, Any]:
    """Register a new domain at Openprovider. ADMIN ONLY. Logged.

    Safety net: voor premium-domeinen is `confirm_premium=true` vereist.
    Anders weigeren we de registratie -- bescherming tegen per-ongeluk
    hoge kosten."""
    from salespilot.integrations.openprovider import OpenproviderError
    require_groups("administrators")(auth)

    full = f"{body.name}.{body.extension}"
    client = await _op_client_from_db(db)
    request_payload = body.model_dump()

    try:
        async with client as c:
            # 1) Availability + premium-check
            avail = await c.check_availability(body.name, body.extension)
            if avail.get("status") != "free":
                detail = f"Niet beschikbaar: status={avail.get('status')}"
                await _audit(
                    db, org_id=auth.org_id, user_id=auth.user_id,
                    action="register", domain_name=full,
                    request_payload=request_payload, response_payload=avail,
                    status="error", error_message=detail,
                )
                raise HTTPException(status_code=400, detail=detail)
            if avail.get("premium") and not body.confirm_premium:
                price = avail.get("price") or {}
                detail = (
                    f"Dit is een premium-domein. Bevestig met confirm_premium=true. "
                    f"Prijs: {price}"
                )
                await _audit(
                    db, org_id=auth.org_id, user_id=auth.user_id,
                    action="register", domain_name=full,
                    request_payload=request_payload, response_payload=avail,
                    status="error", error_message="premium not confirmed",
                )
                raise HTTPException(status_code=400, detail=detail)

            # 2) Echte registratie
            r = await c.register_domain(
                name=body.name, extension=body.extension,
                period=body.period,
                owner_handle=body.owner_handle,
                admin_handle=body.admin_handle,
                tech_handle=body.tech_handle,
                billing_handle=body.billing_handle,
                name_servers=body.name_servers,
                auto_renew=body.auto_renew,
            )
    except HTTPException:
        raise
    except OpenproviderError as e:
        await _audit(
            db, org_id=auth.org_id, user_id=auth.user_id,
            action="register", domain_name=full,
            request_payload=request_payload, response_payload={},
            status="error", error_message=str(e)[:500],
        )
        raise HTTPException(status_code=502, detail=str(e))

    # 3) Domain row in DB aanmaken zodat hij meteen zichtbaar is
    op_id = str(r.get("id") or "")
    dom = OpenproviderDomain(
        id=uuid4(), org_id=auth.org_id, op_id=op_id or f"pending:{uuid4()}",
        name=full, extension=body.extension, status="active",
        auto_renew=body.auto_renew,
        registered_at=datetime.now(UTC),
        nameservers=body.name_servers or [], raw=r,
    )
    db.add(dom)
    await db.flush()

    if body.company_id:
        db.add(OpenproviderCompanyLink(
            id=uuid4(), org_id=auth.org_id,
            domain_id=dom.id, company_id=body.company_id,
            notes=body.notes,
        ))
        await db.flush()

    await _audit(
        db, org_id=auth.org_id, user_id=auth.user_id,
        action="register", domain_name=full, domain_id=dom.id,
        request_payload=request_payload, response_payload=r,
        status="ok",
    )
    return {"ok": True, "domain": full, "openprovider_id": op_id, "domain_id": str(dom.id)}


# ----- Auto-renew toggle (zachte opzegging, omkeerbaar) -----

class AutoRenewBody(BaseModel):
    auto_renew: bool


@op_router.put("/domains/{domain_id}/autorenew")
async def update_autorenew(
    domain_id: UUID, body: AutoRenewBody, auth: CurrentAuth, db: Db,
) -> dict[str, Any]:
    from salespilot.integrations.openprovider import OpenproviderError
    require_groups("administrators")(auth)
    dom = (await db.execute(
        select(OpenproviderDomain).where(OpenproviderDomain.id == domain_id)
    )).scalar_one_or_none()
    if dom is None:
        raise HTTPException(status_code=404, detail="Domein niet gevonden")
    if dom.op_id.startswith("manual:") or dom.op_id.startswith("pending:"):
        raise HTTPException(
            status_code=400,
            detail="Dit domein staat niet in Openprovider (handmatig of pending). Auto-renew kan alleen voor live domeinen.",
        )

    client = await _op_client_from_db(db)
    action = "auto_renew_on" if body.auto_renew else "auto_renew_off"
    try:
        async with client as c:
            r = await c.update_autorenew(int(dom.op_id), body.auto_renew)
    except OpenproviderError as e:
        await _audit(
            db, org_id=auth.org_id, user_id=auth.user_id,
            action=action, domain_name=dom.name, domain_id=dom.id,
            request_payload={"auto_renew": body.auto_renew}, response_payload={},
            status="error", error_message=str(e)[:500],
        )
        raise HTTPException(status_code=502, detail=str(e))
    dom.auto_renew = body.auto_renew
    await db.flush()
    await _audit(
        db, org_id=auth.org_id, user_id=auth.user_id,
        action=action, domain_name=dom.name, domain_id=dom.id,
        request_payload={"auto_renew": body.auto_renew},
        response_payload=r or {}, status="ok",
    )
    return {"ok": True, "auto_renew": body.auto_renew}


# ----- Hard cancel (binnen grace, NIET reversible) -----

@op_router.delete("/domains/{domain_id}/cancel")
async def cancel_domain_registration(
    domain_id: UUID, auth: CurrentAuth, db: Db,
    confirm: bool = Query(False, description="Must be true"),
    confirm_irreversible: bool = Query(False, description="Must be true"),
) -> dict[str, Any]:
    """Harde cancel binnen grace-period (~5 dagen na registratie).
    Dubbele confirm vereist. NIET reversible.

    Voor reguliere opzegging buiten grace: gebruik PUT autorenew=false
    en laat het domein gewoon expireren."""
    from salespilot.integrations.openprovider import OpenproviderError
    require_groups("administrators")(auth)
    if not (confirm and confirm_irreversible):
        raise HTTPException(
            status_code=400,
            detail="Beide confirm=true en confirm_irreversible=true vereist. Deze actie kan NIET ongedaan worden.",
        )
    dom = (await db.execute(
        select(OpenproviderDomain).where(OpenproviderDomain.id == domain_id)
    )).scalar_one_or_none()
    if dom is None:
        raise HTTPException(status_code=404, detail="Domein niet gevonden")
    if dom.op_id.startswith("manual:") or dom.op_id.startswith("pending:"):
        raise HTTPException(status_code=400, detail="Niet een live Openprovider-domein.")

    client = await _op_client_from_db(db)
    try:
        async with client as c:
            r = await c.cancel_domain(int(dom.op_id))
    except OpenproviderError as e:
        await _audit(
            db, org_id=auth.org_id, user_id=auth.user_id,
            action="cancel", domain_name=dom.name, domain_id=dom.id,
            request_payload={"confirm": True}, response_payload={},
            status="error", error_message=str(e)[:500],
        )
        raise HTTPException(status_code=502, detail=str(e))
    dom.status = "cancelled"
    await db.flush()
    await _audit(
        db, org_id=auth.org_id, user_id=auth.user_id,
        action="cancel", domain_name=dom.name, domain_id=dom.id,
        request_payload={"confirm": True}, response_payload=r or {}, status="ok",
    )
    return {"ok": True, "cancelled": dom.name}


# ----- Audit log viewer -----

class AuditLogRow(BaseModel):
    id: UUID
    user_id: UUID | None
    user_email: str | None = None
    action: str
    domain_name: str | None
    domain_id: UUID | None
    status: str
    error_message: str | None
    occurred_at: datetime


@op_router.get("/audit-log", response_model=list[AuditLogRow])
async def list_audit_log(
    auth: CurrentAuth, db: Db,
    limit: int = Query(100, ge=1, le=500),
) -> list[AuditLogRow]:
    require_groups("administrators")(auth)
    from salespilot.models.auth import User
    rows = (await db.execute(
        select(OpenproviderAuditLog, User)
        .outerjoin(User, User.id == OpenproviderAuditLog.user_id)
        .order_by(desc(OpenproviderAuditLog.occurred_at))
        .limit(limit)
    )).all()
    return [
        AuditLogRow(
            id=a.id, user_id=a.user_id,
            user_email=u.email if u else None,
            action=a.action, domain_name=a.domain_name,
            domain_id=a.domain_id, status=a.status,
            error_message=a.error_message, occurred_at=a.occurred_at,
        )
        for a, u in rows
    ]
