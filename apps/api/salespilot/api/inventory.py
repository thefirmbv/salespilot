"""Employees + asset inventory endpoints.

Eigen medewerkers van IT-Gemak met de assets die ze beheren:
auto (kenteken), telefoon (IMEI), laptop (serial), overig.

Type-specifieke velden zitten in `details` JSONB-veld zodat
nieuwe asset-types geen schema-migratie vereisen.

Voor toekomstige NMBRS-koppeling staan `nmbrs_employee_id` en
`nmbrs_company_id` al klaar (migration 0021) maar de import
werkt nog niet -- huidige NMBRS-token is SOAP-only en mist de
benodigde username (= email).
"""

from __future__ import annotations

from datetime import date, datetime, UTC
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy import select, delete, func

from salespilot.deps import CurrentAuth, Db
from salespilot.models.inventory import Employee, EmployeeAsset


router = APIRouter(prefix="/inventory", tags=["inventory"])


AssetType = Literal["vehicle", "phone", "laptop", "other"]


# ----- Pydantic schemas ----------------------------------------------


class AssetIn(BaseModel):
    asset_type: AssetType
    label: str = Field(..., min_length=1, max_length=160)
    identifier: str | None = None
    details: dict = Field(default_factory=dict)
    assigned_at: date | None = None
    returned_at: date | None = None


class AssetOut(AssetIn):
    id: UUID
    employee_id: UUID
    created_at: datetime
    updated_at: datetime


class EmployeeIn(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=160)
    email: EmailStr | None = None
    phone: str | None = None
    role: str | None = None
    status: Literal["active", "inactive", "leave"] = "active"
    started_at: date | None = None
    ended_at: date | None = None
    notes: str | None = None


class EmployeeOut(EmployeeIn):
    id: UUID
    nmbrs_employee_id: str | None
    nmbrs_company_id: str | None
    halopsa_agent_id: int | None
    halopsa_agent_name: str | None
    asset_count: int = 0
    created_at: datetime
    updated_at: datetime


class EmployeeDetail(EmployeeOut):
    assets: list[AssetOut]


# ----- Helpers -------------------------------------------------------


def _to_employee_out(e: Employee, asset_count: int = 0) -> EmployeeOut:
    return EmployeeOut(
        id=e.id, full_name=e.full_name, email=e.email, phone=e.phone,
        role=e.role, status=e.status,
        started_at=e.started_at, ended_at=e.ended_at, notes=e.notes,
        nmbrs_employee_id=e.nmbrs_employee_id,
        nmbrs_company_id=e.nmbrs_company_id,
        halopsa_agent_id=e.halopsa_agent_id,
        halopsa_agent_name=e.halopsa_agent_name,
        asset_count=asset_count,
        created_at=e.created_at, updated_at=e.updated_at,
    )


def _to_asset_out(a: EmployeeAsset) -> AssetOut:
    return AssetOut(
        id=a.id, employee_id=a.employee_id,
        asset_type=a.asset_type, label=a.label, identifier=a.identifier,
        details=a.details or {},
        assigned_at=a.assigned_at, returned_at=a.returned_at,
        created_at=a.created_at, updated_at=a.updated_at,
    )


# ----- Employee endpoints --------------------------------------------


@router.get("/employees", response_model=list[EmployeeOut])
async def list_employees(auth: CurrentAuth, db: Db) -> list[EmployeeOut]:
    """Lijst medewerkers + aantal assets per medewerker."""
    q = (
        select(
            Employee,
            func.count(EmployeeAsset.id).label("asset_count"),
        )
        .outerjoin(EmployeeAsset, EmployeeAsset.employee_id == Employee.id)
        .group_by(Employee.id)
        .order_by(Employee.full_name)
    )
    rows = (await db.execute(q)).all()
    return [_to_employee_out(e, int(c or 0)) for e, c in rows]


@router.get("/employees/{employee_id}", response_model=EmployeeDetail)
async def get_employee(
    auth: CurrentAuth, db: Db, employee_id: UUID,
) -> EmployeeDetail:
    """Eén medewerker met alle assets."""
    e = (
        await db.execute(select(Employee).where(Employee.id == employee_id))
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(status_code=404, detail="employee not found")
    assets = (
        await db.execute(
            select(EmployeeAsset)
            .where(EmployeeAsset.employee_id == employee_id)
            .order_by(EmployeeAsset.asset_type, EmployeeAsset.created_at)
        )
    ).scalars().all()
    base = _to_employee_out(e, len(assets))
    return EmployeeDetail(**base.model_dump(), assets=[_to_asset_out(a) for a in assets])


@router.post("/employees", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
async def create_employee(
    auth: CurrentAuth, db: Db, data: EmployeeIn,
) -> EmployeeOut:
    """Maak een medewerker aan. Email moet uniek zijn binnen de org."""
    now = datetime.now(UTC)
    e = Employee(
        id=uuid4(), org_id=auth.org_id,
        full_name=data.full_name,
        email=str(data.email) if data.email else None,
        phone=data.phone, role=data.role, status=data.status,
        started_at=data.started_at, ended_at=data.ended_at, notes=data.notes,
        created_at=now, updated_at=now,
    )
    db.add(e)
    try:
        await db.flush()
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"duplicate or invalid: {exc}")
    return _to_employee_out(e, 0)


@router.put("/employees/{employee_id}", response_model=EmployeeOut)
async def update_employee(
    auth: CurrentAuth, db: Db, employee_id: UUID, data: EmployeeIn,
) -> EmployeeOut:
    e = (
        await db.execute(select(Employee).where(Employee.id == employee_id))
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(status_code=404, detail="employee not found")
    e.full_name = data.full_name
    e.email = str(data.email) if data.email else None
    e.phone = data.phone
    e.role = data.role
    e.status = data.status
    e.started_at = data.started_at
    e.ended_at = data.ended_at
    e.notes = data.notes
    e.updated_at = datetime.now(UTC)
    await db.flush()
    # asset_count via aparte query (kort lookup)
    count = (
        await db.execute(
            select(func.count(EmployeeAsset.id))
            .where(EmployeeAsset.employee_id == employee_id)
        )
    ).scalar_one()
    return _to_employee_out(e, int(count or 0))


@router.delete("/employees/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_employee(
    auth: CurrentAuth, db: Db, employee_id: UUID,
) -> None:
    """Verwijder medewerker + alle assets (cascade)."""
    r = await db.execute(
        delete(Employee).where(Employee.id == employee_id)
    )
    if r.rowcount == 0:
        raise HTTPException(status_code=404, detail="employee not found")


# ----- Asset endpoints -----------------------------------------------


@router.post(
    "/employees/{employee_id}/assets",
    response_model=AssetOut, status_code=status.HTTP_201_CREATED,
)
async def add_asset(
    auth: CurrentAuth, db: Db, employee_id: UUID, data: AssetIn,
) -> AssetOut:
    """Asset aan medewerker toevoegen."""
    # Verifieer employee bestaat
    e = (
        await db.execute(select(Employee).where(Employee.id == employee_id))
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(status_code=404, detail="employee not found")

    now = datetime.now(UTC)
    a = EmployeeAsset(
        id=uuid4(), org_id=auth.org_id,
        employee_id=employee_id,
        asset_type=data.asset_type,
        label=data.label,
        identifier=data.identifier,
        details=data.details or {},
        assigned_at=data.assigned_at,
        returned_at=data.returned_at,
        created_at=now, updated_at=now,
    )
    db.add(a)
    await db.flush()
    return _to_asset_out(a)


@router.put("/assets/{asset_id}", response_model=AssetOut)
async def update_asset(
    auth: CurrentAuth, db: Db, asset_id: UUID, data: AssetIn,
) -> AssetOut:
    a = (
        await db.execute(select(EmployeeAsset).where(EmployeeAsset.id == asset_id))
    ).scalar_one_or_none()
    if a is None:
        raise HTTPException(status_code=404, detail="asset not found")
    a.asset_type = data.asset_type
    a.label = data.label
    a.identifier = data.identifier
    a.details = data.details or {}
    a.assigned_at = data.assigned_at
    a.returned_at = data.returned_at
    a.updated_at = datetime.now(UTC)
    await db.flush()
    return _to_asset_out(a)


@router.delete("/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    auth: CurrentAuth, db: Db, asset_id: UUID,
) -> None:
    r = await db.execute(
        delete(EmployeeAsset).where(EmployeeAsset.id == asset_id)
    )
    if r.rowcount == 0:
        raise HTTPException(status_code=404, detail="asset not found")





# ----- HaloPSA agent matching ----------------------------------------


class HaloPSAAgent(BaseModel):
    id: int
    name: str
    email: str | None
    inactive: bool = False


@router.get("/halopsa-agents", response_model=list[HaloPSAAgent])
async def list_halopsa_agents(auth: CurrentAuth, db: Db) -> list[HaloPSAAgent]:
    """Lijst alle HaloPSA agents incl. disabled, voor matching-dropdown."""
    from salespilot.models.integrations import Integration
    from salespilot.integrations.halopsa import HaloPSAClient, HaloPSACredentials

    integ = (
        await db.execute(
            select(Integration).where(Integration.kind == "halopsa")
        )
    ).scalar_one_or_none()
    if not integ:
        raise HTTPException(status_code=400, detail="HaloPSA not configured")

    cfg = integ.config_json
    creds = HaloPSACredentials(
        base_url=cfg.get("base_url", ""),
        client_id=cfg.get("client_id", ""),
        client_secret=cfg.get("client_secret", ""),
        tenant_id=cfg.get("tenant_id"),
    )

    agents: list[HaloPSAAgent] = []
    async with HaloPSAClient(creds) as c:
        # Met disabled=true krijgen we alle agents
        d = await c._request("GET", "/api/Agent",
                             params={"count": 200, "includedisabled": "true"})
        if isinstance(d, list):
            for a in d:
                aid = a.get("id")
                if aid is None or aid == 1:  # skip 'Unassigned'
                    continue
                agents.append(HaloPSAAgent(
                    id=aid,
                    name=a.get("name") or a.get("namewithinactive") or "",
                    email=a.get("email") or None,
                    inactive=bool(a.get("inactive") or False),
                ))
    agents.sort(key=lambda x: x.name.lower())
    return agents


class HaloPSALinkIn(BaseModel):
    halopsa_agent_id: int | None  # None = ontkoppelen


@router.put("/employees/{employee_id}/halopsa-link", response_model=EmployeeOut)
async def link_halopsa_agent(
    auth: CurrentAuth, db: Db, employee_id: UUID, data: HaloPSALinkIn,
) -> EmployeeOut:
    """Koppel of ontkoppel een HaloPSA-agent aan een medewerker."""
    e = (
        await db.execute(select(Employee).where(Employee.id == employee_id))
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(status_code=404, detail="employee not found")

    if data.halopsa_agent_id is None:
        e.halopsa_agent_id = None
        e.halopsa_agent_name = None
    else:
        # Resolve naam via HaloPSA
        from salespilot.models.integrations import Integration
        from salespilot.integrations.halopsa import HaloPSAClient, HaloPSACredentials
        integ = (
            await db.execute(
                select(Integration).where(Integration.kind == "halopsa")
            )
        ).scalar_one_or_none()
        if not integ:
            raise HTTPException(status_code=400, detail="HaloPSA not configured")
        cfg = integ.config_json
        creds = HaloPSACredentials(
            base_url=cfg.get("base_url", ""),
            client_id=cfg.get("client_id", ""),
            client_secret=cfg.get("client_secret", ""),
            tenant_id=cfg.get("tenant_id"),
        )
        async with HaloPSAClient(creds) as c:
            d = await c._request("GET", "/api/Agent",
                                 params={"count": 200, "includedisabled": "true"})
        agent = next(
            (a for a in (d if isinstance(d, list) else []) if a.get("id") == data.halopsa_agent_id),
            None,
        )
        if agent is None:
            raise HTTPException(status_code=404, detail="HaloPSA agent niet gevonden")
        e.halopsa_agent_id = data.halopsa_agent_id
        e.halopsa_agent_name = agent.get("name") or agent.get("namewithinactive") or ""

    e.updated_at = datetime.now(UTC)
    await db.flush()
    count = (
        await db.execute(
            select(func.count(EmployeeAsset.id))
            .where(EmployeeAsset.employee_id == employee_id)
        )
    ).scalar_one()
    return _to_employee_out(e, int(count or 0))


# ----- NMBRS import (placeholder) ------------------------------------


@router.post("/nmbrs/import", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def import_from_nmbrs(auth: CurrentAuth, db: Db) -> dict:
    """Placeholder voor NMBRS-medewerker import.

    Werkt NIET met huidig token. NMBRS REST API vereist OAuth 2.0 met
    client_id + client_secret + subscription_key (via developer.nmbrs.com).
    Het token dat we nu hebben is SOAP-only en heeft username (email)
    nodig die ontbreekt.
    """
    raise HTTPException(
        status_code=501,
        detail=(
            "NMBRS import is not yet configured. Need either: "
            "(a) NMBRS username + SOAP token (deprecated 2027), or "
            "(b) OAuth credentials via developer.nmbrs.com registration."
        ),
    )
