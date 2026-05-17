"""UniFi API endpoints.

Read-only views over the polled state. All data comes from the postgres
mirror; live UniFi calls only happen during /sync.

Routes:
    GET /unifi/dashboard           -- aggregate KPIs + per-model breakdown
    GET /unifi/hosts               -- list of Dream Machines + status
    GET /unifi/hosts/{id}          -- detail of one host
    GET /unifi/hosts/{id}/devices  -- managed devices on that host
    GET /unifi/devices             -- flat list of all devices (optionally filtered)
    GET /unifi/incidents           -- state_events feed for downtime view
    GET /unifi/company/{id}/device-count
                                   -- billable device count for one company
    POST /unifi/hosts/{id}/link-company
                                   -- bind a host to a SalesPilot company
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import selectinload

from salespilot.deps import CurrentAuth, Db
from salespilot.models.crm import Company
from salespilot.models.unifi import (
    UnifiCompanyLink, UnifiDevice, UnifiHost, UnifiSite, UnifiStateEvent,
)


router = APIRouter(prefix="/unifi", tags=["unifi"])


# ----------------------------------------------------------------------
# Dashboard
# ----------------------------------------------------------------------


class ModelBreakdown(BaseModel):
    model_short: str
    count: int


class DashboardResponse(BaseModel):
    hosts_total: int
    hosts_online: int
    devices_total: int
    devices_online: int
    devices_offline: int
    devices_with_updates: int
    incidents_24h: int
    last_polled: datetime | None
    by_model: list[ModelBreakdown]


@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(auth: CurrentAuth, db: Db) -> DashboardResponse:
    hosts_total = (await db.execute(select(func.count(UnifiHost.id)))).scalar() or 0
    hosts_online = (
        await db.execute(select(func.count(UnifiHost.id)).where(UnifiHost.is_online.is_(True)))
    ).scalar() or 0
    devices_total = (await db.execute(select(func.count(UnifiDevice.id)))).scalar() or 0
    devices_online = (
        await db.execute(select(func.count(UnifiDevice.id)).where(UnifiDevice.status == "online"))
    ).scalar() or 0
    devices_offline = (
        await db.execute(select(func.count(UnifiDevice.id)).where(UnifiDevice.status == "offline"))
    ).scalar() or 0
    devices_with_updates = (
        await db.execute(
            select(func.count(UnifiDevice.id)).where(
                UnifiDevice.firmware_status != "upToDate",
                UnifiDevice.firmware_status.is_not(None),
            )
        )
    ).scalar() or 0
    incidents_24h = (
        await db.execute(
            select(func.count(UnifiStateEvent.id)).where(
                UnifiStateEvent.occurred_at >= datetime.now(UTC) - timedelta(hours=24),
            )
        )
    ).scalar() or 0
    last_polled = (
        await db.execute(select(func.max(UnifiHost.last_polled)))
    ).scalar()

    by_model_rows = (
        await db.execute(
            select(
                func.coalesce(UnifiDevice.model_short, "?"),
                func.count(UnifiDevice.id),
            )
            .group_by(UnifiDevice.model_short)
            .order_by(desc(func.count(UnifiDevice.id)))
            .limit(20)
        )
    ).all()
    by_model = [ModelBreakdown(model_short=m, count=n) for m, n in by_model_rows]

    return DashboardResponse(
        hosts_total=hosts_total,
        hosts_online=hosts_online,
        devices_total=devices_total,
        devices_online=devices_online,
        devices_offline=devices_offline,
        devices_with_updates=devices_with_updates,
        incidents_24h=incidents_24h,
        last_polled=last_polled,
        by_model=by_model,
    )


# ----------------------------------------------------------------------
# Hosts
# ----------------------------------------------------------------------


class HostRow(BaseModel):
    id: UUID
    ubnt_host_id: str
    name: str
    model_short: str | None
    ip_address: str | None
    owner_email: str | None
    is_online: bool
    is_blocked: bool
    last_connection_change: datetime | None
    last_polled: datetime | None
    device_count: int
    devices_online: int
    devices_offline: int
    company_id: UUID | None
    company_name: str | None


@router.get("/hosts", response_model=list[HostRow])
async def list_hosts(
    auth: CurrentAuth, db: Db,
    status: str | None = Query(default=None, description="online|offline"),
) -> list[HostRow]:
    rows = (await db.execute(select(UnifiHost).order_by(UnifiHost.name))).scalars().all()

    # All links + companies in one query
    links = {
        l.host_id: l
        for l in (await db.execute(select(UnifiCompanyLink))).scalars()
    }
    company_ids = {l.company_id for l in links.values()}
    companies = {}
    if company_ids:
        companies = {
            c.id: c
            for c in (
                await db.execute(select(Company).where(Company.id.in_(company_ids)))
            ).scalars()
        }

    # Device counts per host in one query
    dev_counts = dict((host_id, (n_total, n_online, n_offline)) for host_id, n_total, n_online, n_offline in (
        await db.execute(
            select(
                UnifiDevice.host_id,
                func.count(UnifiDevice.id),
                func.count(UnifiDevice.id).filter(UnifiDevice.status == "online"),
                func.count(UnifiDevice.id).filter(UnifiDevice.status == "offline"),
            ).group_by(UnifiDevice.host_id)
        )
    ).all())

    out: list[HostRow] = []
    for h in rows:
        if status == "online" and not h.is_online:
            continue
        if status == "offline" and h.is_online:
            continue
        n_total, n_online, n_offline = dev_counts.get(h.id, (0, 0, 0))
        link = links.get(h.id)
        comp = companies.get(link.company_id) if link else None
        out.append(HostRow(
            id=h.id, ubnt_host_id=h.ubnt_host_id, name=h.name,
            model_short=h.model_short, ip_address=h.ip_address,
            owner_email=h.owner_email,
            is_online=h.is_online, is_blocked=h.is_blocked,
            last_connection_change=h.last_connection_change,
            last_polled=h.last_polled,
            device_count=n_total, devices_online=n_online,
            devices_offline=n_offline,
            company_id=link.company_id if link else None,
            company_name=comp.name if comp else None,
        ))
    return out


# ----------------------------------------------------------------------
# Devices
# ----------------------------------------------------------------------


class DeviceRow(BaseModel):
    id: UUID
    ubnt_device_id: str
    host_id: UUID
    host_name: str | None = None
    mac: str | None
    name: str
    model: str | None
    model_short: str | None
    product_line: str | None
    ip_address: str | None
    firmware_version: str | None
    firmware_status: str | None
    update_available: str | None
    is_console: bool
    status: str
    startup_time: datetime | None
    halopsa_asset_id: int | None
    last_polled: datetime | None


@router.get("/hosts/{host_id}/devices", response_model=list[DeviceRow])
async def list_devices_for_host(
    host_id: UUID, auth: CurrentAuth, db: Db,
) -> list[DeviceRow]:
    host = (
        await db.execute(select(UnifiHost).where(UnifiHost.id == host_id))
    ).scalar_one_or_none()
    if host is None:
        raise HTTPException(status_code=404, detail="Host niet gevonden")
    rows = (
        await db.execute(
            select(UnifiDevice).where(UnifiDevice.host_id == host_id).order_by(UnifiDevice.name)
        )
    ).scalars().all()
    return [
        DeviceRow(
            id=d.id, ubnt_device_id=d.ubnt_device_id, host_id=d.host_id, host_name=host.name,
            mac=d.mac, name=d.name, model=d.model, model_short=d.model_short,
            product_line=d.product_line, ip_address=d.ip_address,
            firmware_version=d.firmware_version, firmware_status=d.firmware_status,
            update_available=d.update_available,
            is_console=d.is_console, status=d.status, startup_time=d.startup_time,
            halopsa_asset_id=d.halopsa_asset_id, last_polled=d.last_polled,
        ) for d in rows
    ]


@router.get("/devices", response_model=list[DeviceRow])
async def list_all_devices(
    auth: CurrentAuth, db: Db,
    status: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
) -> list[DeviceRow]:
    q = select(UnifiDevice, UnifiHost.name).join(
        UnifiHost, UnifiHost.id == UnifiDevice.host_id,
    ).order_by(UnifiDevice.name).limit(limit)
    if status:
        q = q.where(UnifiDevice.status == status)
    rows = (await db.execute(q)).all()
    return [
        DeviceRow(
            id=d.id, ubnt_device_id=d.ubnt_device_id, host_id=d.host_id, host_name=hn,
            mac=d.mac, name=d.name, model=d.model, model_short=d.model_short,
            product_line=d.product_line, ip_address=d.ip_address,
            firmware_version=d.firmware_version, firmware_status=d.firmware_status,
            update_available=d.update_available,
            is_console=d.is_console, status=d.status, startup_time=d.startup_time,
            halopsa_asset_id=d.halopsa_asset_id, last_polled=d.last_polled,
        ) for d, hn in rows
    ]


# ----------------------------------------------------------------------
# Incidents feed
# ----------------------------------------------------------------------


class IncidentRow(BaseModel):
    id: UUID
    entity_kind: str
    entity_id: UUID
    entity_name: str | None
    previous_status: str | None
    new_status: str
    occurred_at: datetime
    snapshot: dict[str, Any]


@router.get("/incidents", response_model=list[IncidentRow])
async def list_incidents(
    auth: CurrentAuth, db: Db,
    hours: int = Query(default=72, ge=1, le=720),
    limit: int = Query(default=200, ge=1, le=2000),
) -> list[IncidentRow]:
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    rows = (
        await db.execute(
            select(UnifiStateEvent)
            .where(UnifiStateEvent.occurred_at >= cutoff)
            .order_by(desc(UnifiStateEvent.occurred_at))
            .limit(limit)
        )
    ).scalars().all()
    return [
        IncidentRow(
            id=r.id, entity_kind=r.entity_kind, entity_id=r.entity_id,
            entity_name=(r.snapshot or {}).get("name"),
            previous_status=r.previous_status, new_status=r.new_status,
            occurred_at=r.occurred_at, snapshot=r.snapshot or {},
        ) for r in rows
    ]


# ----------------------------------------------------------------------
# Company linking + billing helpers
# ----------------------------------------------------------------------


class LinkCompanyRequest(BaseModel):
    company_id: UUID
    notes: str | None = None


@router.post("/hosts/{host_id}/link-company")
async def link_company(
    host_id: UUID, body: LinkCompanyRequest, auth: CurrentAuth, db: Db,
) -> dict[str, Any]:
    host = (
        await db.execute(select(UnifiHost).where(UnifiHost.id == host_id))
    ).scalar_one_or_none()
    if host is None:
        raise HTTPException(status_code=404, detail="Host niet gevonden")
    company = (
        await db.execute(select(Company).where(Company.id == body.company_id))
    ).scalar_one_or_none()
    if company is None:
        raise HTTPException(status_code=404, detail="Company niet gevonden")
    existing = (
        await db.execute(select(UnifiCompanyLink).where(UnifiCompanyLink.host_id == host_id))
    ).scalar_one_or_none()
    if existing:
        existing.company_id = body.company_id
        existing.notes = body.notes
    else:
        db.add(UnifiCompanyLink(
            id=uuid4(), org_id=auth.org_id,
            host_id=host_id, company_id=body.company_id, notes=body.notes,
        ))
    await db.flush()
    return {"ok": True, "host_name": host.name, "company_name": company.name}


@router.delete("/hosts/{host_id}/link-company")
async def unlink_company(host_id: UUID, auth: CurrentAuth, db: Db) -> dict[str, Any]:
    existing = (
        await db.execute(select(UnifiCompanyLink).where(UnifiCompanyLink.host_id == host_id))
    ).scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.flush()
    return {"ok": True}


class CompanyDeviceCount(BaseModel):
    company_id: UUID
    company_name: str
    host_count: int
    device_count: int
    devices_online: int
    devices_offline: int


@router.get("/company/{company_id}/device-count", response_model=CompanyDeviceCount)
async def company_device_count(
    company_id: UUID, auth: CurrentAuth, db: Db,
) -> CompanyDeviceCount:
    """Billable device count for one SalesPilot company.

    Sums devices across ALL hosts linked to that company. Used by HaloPSA
    recurring invoice line for "UniFi monitoring" -- one fixed price per
    device, regardless of model.
    """
    company = (
        await db.execute(select(Company).where(Company.id == company_id))
    ).scalar_one_or_none()
    if company is None:
        raise HTTPException(status_code=404, detail="Company niet gevonden")
    link_host_ids = [
        l.host_id for l in (
            await db.execute(
                select(UnifiCompanyLink).where(UnifiCompanyLink.company_id == company_id)
            )
        ).scalars()
    ]
    if not link_host_ids:
        return CompanyDeviceCount(
            company_id=company_id, company_name=company.name,
            host_count=0, device_count=0, devices_online=0, devices_offline=0,
        )
    n_total = (
        await db.execute(
            select(func.count(UnifiDevice.id)).where(UnifiDevice.host_id.in_(link_host_ids))
        )
    ).scalar() or 0
    n_online = (
        await db.execute(
            select(func.count(UnifiDevice.id)).where(
                UnifiDevice.host_id.in_(link_host_ids),
                UnifiDevice.status == "online",
            )
        )
    ).scalar() or 0
    n_offline = (
        await db.execute(
            select(func.count(UnifiDevice.id)).where(
                UnifiDevice.host_id.in_(link_host_ids),
                UnifiDevice.status == "offline",
            )
        )
    ).scalar() or 0
    return CompanyDeviceCount(
        company_id=company_id, company_name=company.name,
        host_count=len(link_host_ids),
        device_count=n_total, devices_online=n_online, devices_offline=n_offline,
    )


# ----------------------------------------------------------------------
# HaloPSA asset sync trigger
# ----------------------------------------------------------------------


@router.post("/sync-halopsa-assets")
async def sync_halopsa_assets(
    auth: CurrentAuth, db: Db,
    company_id: UUID | None = Query(default=None, description="Limit to one company"),
) -> dict[str, Any]:
    """Mirror all linked UniFi devices into HaloPSA Assets under type
    'UniFi Devices' (or whatever the integration config says)."""
    from sqlalchemy import select as _select
    from salespilot.integrations.halopsa import HaloPSAClient, HaloPSACredentials, HaloPSAError
    from salespilot.integrations.unifi_halopsa_sync import sync_unifi_devices_to_halopsa
    from salespilot.models.integrations import Integration

    halopsa_row = (
        await db.execute(_select(Integration).where(Integration.kind == "halopsa"))
    ).scalar_one_or_none()
    if halopsa_row is None or not halopsa_row.is_enabled:
        raise HTTPException(status_code=400, detail="HaloPSA niet ingesteld.")

    unifi_row = (
        await db.execute(_select(Integration).where(Integration.kind == "unifi"))
    ).scalar_one_or_none()
    asset_type = (unifi_row.config_json or {}).get("asset_type") if unifi_row else None

    cfg = halopsa_row.config_json or {}
    creds = HaloPSACredentials(
        base_url=cfg.get("base_url", ""),
        client_id=cfg.get("client_id", ""),
        client_secret=cfg.get("client_secret", ""),
        tenant_id=cfg.get("tenant_id"),
        scopes=cfg.get("scopes") or "all",
    )
    try:
        async with HaloPSAClient(creds) as halo_c:
            result = await sync_unifi_devices_to_halopsa(
                db, org_id=auth.org_id, halopsa_client=halo_c,
                asset_type_name=asset_type or "UniFi Devices",
                company_id=company_id,
            )
    except HaloPSAError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return result


# ----------------------------------------------------------------------
# Prometheus exporter -- /unifi/metrics
# Plain-text exposition format. Grafana scrapes this via Prometheus.
# ----------------------------------------------------------------------


from fastapi.responses import PlainTextResponse


@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics(auth: CurrentAuth, db: Db) -> str:
    """Prometheus-compatible metrics. Labels: host_name, model_short.

    Grafana queries:
        sum by (host_name) (unifi_device_online)
        unifi_host_up
        unifi_devices_with_updates
        rate(unifi_state_change_total[15m])
    """
    lines: list[str] = []

    # Host-level: is_online (0/1)
    rows = (await db.execute(select(UnifiHost))).scalars().all()
    lines.append("# HELP unifi_host_up Whether a UniFi host (console) is reachable")
    lines.append("# TYPE unifi_host_up gauge")
    for h in rows:
        name = (h.name or "?").replace('"', "'")
        model = h.model_short or "?"
        lines.append(
            f'unifi_host_up{{host_id="{h.id}",host_name="{name}",model="{model}"}} '
            f'{1 if h.is_online else 0}'
        )

    # Device-level: online count per host
    dev_counts = (await db.execute(
        select(
            UnifiDevice.host_id,
            UnifiDevice.status,
            func.count(UnifiDevice.id),
        ).group_by(UnifiDevice.host_id, UnifiDevice.status)
    )).all()
    host_lookup = {h.id: h for h in rows}
    lines.append("")
    lines.append("# HELP unifi_devices_total Devices grouped by host and status")
    lines.append("# TYPE unifi_devices_total gauge")
    for host_id, status, n in dev_counts:
        h = host_lookup.get(host_id)
        if not h:
            continue
        name = (h.name or "?").replace('"', "'")
        lines.append(
            f'unifi_devices_total{{host_id="{host_id}",host_name="{name}",status="{status}"}} {n}'
        )

    # State changes (last 24h) counter
    incidents_24h = (await db.execute(
        select(func.count(UnifiStateEvent.id)).where(
            UnifiStateEvent.occurred_at >= datetime.now(UTC) - timedelta(hours=24),
        )
    )).scalar() or 0
    lines.append("")
    lines.append("# HELP unifi_state_changes_24h State transitions in the last 24 hours")
    lines.append("# TYPE unifi_state_changes_24h gauge")
    lines.append(f"unifi_state_changes_24h {incidents_24h}")

    # Firmware updates available
    updates_avail = (await db.execute(
        select(func.count(UnifiDevice.id)).where(
            UnifiDevice.firmware_status == "updateAvailable",
        )
    )).scalar() or 0
    lines.append("")
    lines.append("# HELP unifi_devices_with_updates Devices reporting a firmware update")
    lines.append("# TYPE unifi_devices_with_updates gauge")
    lines.append(f"unifi_devices_with_updates {updates_avail}")

    # Company-level device counts (for billing visibility in Grafana)
    company_counts = (await db.execute(
        select(
            Company.id, Company.name,
            func.count(UnifiDevice.id),
        )
        .join(UnifiCompanyLink, UnifiCompanyLink.company_id == Company.id)
        .join(UnifiDevice, UnifiDevice.host_id == UnifiCompanyLink.host_id)
        .group_by(Company.id, Company.name)
    )).all()
    if company_counts:
        lines.append("")
        lines.append("# HELP unifi_company_device_count Billable UniFi device count per company")
        lines.append("# TYPE unifi_company_device_count gauge")
        for cid, cname, n in company_counts:
            cname_s = (cname or "?").replace('"', "'")
            lines.append(
                f'unifi_company_device_count{{company_id="{cid}",company_name="{cname_s}"}} {n}'
            )

    lines.append("")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Company-link overview (1 klant : N hosts)
# ----------------------------------------------------------------------


class HostStub(BaseModel):
    host_id: UUID
    host_name: str
    model_short: str | None
    is_online: bool
    device_count: int
    devices_online: int


class CompanyLinkSummary(BaseModel):
    company_id: UUID
    company_name: str
    halopsa_id: int | None
    hosts: list[HostStub]
    total_devices: int
    total_devices_online: int
    total_devices_offline: int


@router.get("/links", response_model=list[CompanyLinkSummary])
async def list_company_links(auth: CurrentAuth, db: Db) -> list[CompanyLinkSummary]:
    """All host->company links grouped by company.

    For the link-overview page: shows how many UniFi hosts each customer
    has and the rolled-up device counts for billing.
    """
    rows = (
        await db.execute(
            select(UnifiCompanyLink, UnifiHost, Company)
            .join(UnifiHost, UnifiHost.id == UnifiCompanyLink.host_id)
            .join(Company, Company.id == UnifiCompanyLink.company_id)
            .order_by(Company.name, UnifiHost.name)
        )
    ).all()

    # Device counts per host
    dev_counts = {
        host_id: (n_total, n_online, n_offline)
        for host_id, n_total, n_online, n_offline in (
            await db.execute(
                select(
                    UnifiDevice.host_id,
                    func.count(UnifiDevice.id),
                    func.count(UnifiDevice.id).filter(UnifiDevice.status == "online"),
                    func.count(UnifiDevice.id).filter(UnifiDevice.status == "offline"),
                ).group_by(UnifiDevice.host_id)
            )
        ).all()
    }

    by_company: dict[UUID, CompanyLinkSummary] = {}
    for link, host, company in rows:
        n_total, n_online, n_offline = dev_counts.get(host.id, (0, 0, 0))
        s = by_company.get(company.id)
        if s is None:
            s = CompanyLinkSummary(
                company_id=company.id,
                company_name=company.name,
                halopsa_id=getattr(company, "halopsa_id", None),
                hosts=[],
                total_devices=0,
                total_devices_online=0,
                total_devices_offline=0,
            )
            by_company[company.id] = s
        s.hosts.append(HostStub(
            host_id=host.id, host_name=host.name,
            model_short=host.model_short, is_online=host.is_online,
            device_count=n_total, devices_online=n_online,
        ))
        s.total_devices += n_total
        s.total_devices_online += n_online
        s.total_devices_offline += n_offline
    return list(by_company.values())
