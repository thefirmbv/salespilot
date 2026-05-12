"""Enriched Deals listing with company + primary contact denormalised in.

The default /deals endpoint returns raw Deal rows. This one joins in the
company name + primary contact (name, email, phone) so the UI can render
without N+1 fetches.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from salespilot.deps import CurrentAuth, Db
from salespilot.models.crm import Company, Contact, Deal, DealStatus, Stage
from salespilot.models.quotation import Quotation

router = APIRouter(prefix="/deals-enriched", tags=["deals"])


class DealEnriched(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    amount: Decimal | None
    currency: str
    status: str
    pipeline_id: UUID
    stage_id: UUID
    stage_name: str | None = None
    company_id: UUID | None
    company_name: str | None = None
    primary_contact_id: UUID | None = None
    primary_contact_name: str | None = None
    primary_contact_email: str | None = None
    primary_contact_phone: str | None = None
    expected_close_date: datetime | None = None
    closed_at: datetime | None = None
    quotation_count: int = 0
    quotation_total: Decimal | None = None
    last_quotation_status: str | None = None
    created_at: datetime
    updated_at: datetime


class DealsSummary(BaseModel):
    open_count: int = 0
    open_amount: Decimal = Decimal("0")
    won_count_30d: int = 0
    won_amount_30d: Decimal = Decimal("0")
    lost_count_30d: int = 0
    lost_amount_30d: Decimal = Decimal("0")
    win_rate_90d: float = 0.0
    stale_open_count: int = 0  # open + no activity in 14 days
    currency: str = "EUR"


def _contact_name(c: Contact | None) -> str | None:
    if c is None:
        return None
    parts = [c.first_name, c.last_name]
    out = " ".join(p for p in parts if p).strip()
    return out or None


@router.get("", response_model=list[DealEnriched])
async def list_deals_enriched(
    auth: CurrentAuth,
    db: Db,
    status: str | None = Query(None, description="comma-separated"),
    company_id: UUID | None = None,
    stage_id: UUID | None = None,
    limit: int = Query(200, le=500),
) -> list[DealEnriched]:
    stmt = select(Deal)
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            stmt = stmt.where(Deal.status.in_(statuses))
    if company_id:
        stmt = stmt.where(Deal.company_id == company_id)
    if stage_id:
        stmt = stmt.where(Deal.stage_id == stage_id)
    stmt = stmt.order_by(Deal.updated_at.desc()).limit(limit)

    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return []

    # Batch the FK lookups so we don't do N queries per row.
    company_ids = {d.company_id for d in rows if d.company_id}
    contact_ids = {d.primary_contact_id for d in rows if d.primary_contact_id}
    stage_ids = {d.stage_id for d in rows}

    companies: dict[UUID, Company] = {}
    if company_ids:
        for c in (await db.execute(select(Company).where(Company.id.in_(company_ids)))).scalars():
            companies[c.id] = c

    contacts: dict[UUID, Contact] = {}
    if contact_ids:
        for c in (await db.execute(select(Contact).where(Contact.id.in_(contact_ids)))).scalars():
            contacts[c.id] = c

    stages: dict[UUID, Stage] = {}
    if stage_ids:
        for s in (await db.execute(select(Stage).where(Stage.id.in_(stage_ids)))).scalars():
            stages[s.id] = s

    # Quotation aggregations per deal (count, sum gross, latest status).
    deal_ids = [d.id for d in rows]
    quote_rows: dict[UUID, list[Quotation]] = {d.id: [] for d in rows}
    quotes = (
        await db.execute(
            select(Quotation).where(Quotation.deal_id.in_(deal_ids))
        )
    ).scalars().all()
    for q in quotes:
        if q.deal_id is not None:
            quote_rows.setdefault(q.deal_id, []).append(q)

    out: list[DealEnriched] = []
    for d in rows:
        company = companies.get(d.company_id) if d.company_id else None
        contact = contacts.get(d.primary_contact_id) if d.primary_contact_id else None
        stage = stages.get(d.stage_id)
        qs = quote_rows.get(d.id, [])
        qs_sorted = sorted(qs, key=lambda q: q.synced_at or q.created_at, reverse=True)
        qtotal: Decimal | None = None
        if qs:
            qtotal = sum(
                (q.amount_gross or q.amount_net or Decimal("0") for q in qs),
                start=Decimal("0"),
            )

        out.append(
            DealEnriched(
                id=d.id,
                name=d.name,
                amount=d.amount,
                currency=d.currency,
                status=d.status.value if hasattr(d.status, "value") else str(d.status),
                pipeline_id=d.pipeline_id,
                stage_id=d.stage_id,
                stage_name=stage.name if stage else None,
                company_id=d.company_id,
                company_name=company.name if company else None,
                primary_contact_id=d.primary_contact_id,
                primary_contact_name=_contact_name(contact),
                primary_contact_email=contact.email if contact else None,
                primary_contact_phone=contact.phone if contact else None,
                expected_close_date=d.expected_close_date,
                closed_at=d.closed_at,
                quotation_count=len(qs),
                quotation_total=qtotal,
                last_quotation_status=qs_sorted[0].status if qs_sorted else None,
                created_at=d.created_at,
                updated_at=d.updated_at,
            )
        )
    return out


@router.get("/summary", response_model=DealsSummary)
async def deals_summary(auth: CurrentAuth, db: Db) -> DealsSummary:
    now = datetime.now(UTC)
    thirty = now - timedelta(days=30)
    ninety = now - timedelta(days=90)
    fourteen = now - timedelta(days=14)

    rows = (await db.execute(select(Deal))).scalars().all()
    open_count = 0
    open_amount = Decimal("0")
    won_30d = 0
    won_amount_30d = Decimal("0")
    lost_30d = 0
    lost_amount_30d = Decimal("0")
    won_90d = 0
    lost_90d = 0
    stale = 0

    for d in rows:
        status = d.status.value if hasattr(d.status, "value") else str(d.status)
        amount = d.amount or Decimal("0")
        if status == "open":
            open_count += 1
            open_amount += amount
            # Stale: no update in 14 days
            ref = d.updated_at or d.created_at
            if ref is not None and ref < fourteen:
                stale += 1
        elif status == "won":
            if d.closed_at and d.closed_at >= thirty:
                won_30d += 1
                won_amount_30d += amount
            if d.closed_at and d.closed_at >= ninety:
                won_90d += 1
        elif status == "lost":
            if d.closed_at and d.closed_at >= thirty:
                lost_30d += 1
                lost_amount_30d += amount
            if d.closed_at and d.closed_at >= ninety:
                lost_90d += 1

    win_rate = 0.0
    if won_90d + lost_90d > 0:
        win_rate = round(won_90d / (won_90d + lost_90d) * 100, 1)

    return DealsSummary(
        open_count=open_count,
        open_amount=open_amount,
        won_count_30d=won_30d,
        won_amount_30d=won_amount_30d,
        lost_count_30d=lost_30d,
        lost_amount_30d=lost_amount_30d,
        win_rate_90d=win_rate,
        stale_open_count=stale,
    )
