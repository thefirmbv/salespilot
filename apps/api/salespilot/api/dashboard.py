"""Dashboard endpoint.

Single GET /dashboard call returns all KPIs and small datasets needed to
render the home page. We aggregate in SQL — no row-by-row loading.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from salespilot.deps import Db
from salespilot.models.crm import (
    Activity,
    Company,
    Contact,
    Deal,
    DealStatus,
    Stage,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _start_of_month(d: datetime) -> datetime:
    return d.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def _open_pipeline_total(db: AsyncSession) -> dict[str, Any]:
    stmt = select(
        func.count().label("count"),
        func.coalesce(func.sum(Deal.amount), 0).label("amount"),
    ).where(Deal.status == DealStatus.OPEN)
    row = (await db.execute(stmt)).one()
    return {"count": int(row.count), "amount": float(row.amount or 0)}


async def _stats_since(
    db: AsyncSession, status: DealStatus, since: datetime
) -> dict[str, Any]:
    stmt = select(
        func.count().label("count"),
        func.coalesce(func.sum(Deal.amount), 0).label("amount"),
    ).where(Deal.status == status, Deal.closed_at >= since)
    row = (await db.execute(stmt)).one()
    return {"count": int(row.count), "amount": float(row.amount or 0)}


async def _win_rate_last_n_days(db: AsyncSession, days: int) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=days)
    stmt = select(
        func.sum(case((Deal.status == DealStatus.WON, 1), else_=0)).label("won"),
        func.sum(case((Deal.status == DealStatus.LOST, 1), else_=0)).label("lost"),
    ).where(Deal.closed_at >= since)
    row = (await db.execute(stmt)).one()
    won = int(row.won or 0)
    lost = int(row.lost or 0)
    total = won + lost
    rate = (won / total) if total > 0 else None
    return {"won": won, "lost": lost, "rate": rate, "window_days": days}


async def _deals_per_stage(db: AsyncSession) -> list[dict[str, Any]]:
    stmt = (
        select(
            Stage.id,
            Stage.name,
            Stage.position,
            Stage.is_won,
            Stage.is_lost,
            func.count(Deal.id).label("count"),
            func.coalesce(func.sum(Deal.amount), 0).label("amount"),
        )
        .outerjoin(Deal, (Deal.stage_id == Stage.id) & (Deal.status == DealStatus.OPEN))
        .group_by(Stage.id)
        .order_by(Stage.position)
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "stage_id": str(r.id),
            "name": r.name,
            "position": r.position,
            "is_won": r.is_won,
            "is_lost": r.is_lost,
            "count": int(r.count or 0),
            "amount": float(r.amount or 0),
        }
        for r in rows
    ]


async def _won_revenue_by_month(db: AsyncSession, months: int) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    # Build the cutoff as N months ago, start-of-month.
    cutoff_year = now.year
    cutoff_month = now.month - (months - 1)
    while cutoff_month < 1:
        cutoff_month += 12
        cutoff_year -= 1
    cutoff = datetime(cutoff_year, cutoff_month, 1, tzinfo=UTC)

    bucket = func.date_trunc("month", Deal.closed_at)
    stmt = (
        select(
            bucket.label("month"),
            func.count().label("count"),
            func.coalesce(func.sum(Deal.amount), 0).label("amount"),
        )
        .where(Deal.status == DealStatus.WON, Deal.closed_at >= cutoff)
        .group_by(bucket)
        .order_by(bucket)
    )
    rows = (await db.execute(stmt)).all()
    by_month = {r.month: r for r in rows}

    # Fill in any empty months so the chart has a continuous x-axis.
    out: list[dict[str, Any]] = []
    y, m = cutoff_year, cutoff_month
    for _ in range(months):
        key = datetime(y, m, 1, tzinfo=UTC)
        r = by_month.get(key)
        out.append(
            {
                "month": key.strftime("%Y-%m"),
                "count": int(r.count) if r else 0,
                "amount": float(r.amount) if r else 0.0,
            }
        )
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


async def _top_open_deals(db: AsyncSession, n: int) -> list[dict[str, Any]]:
    stmt = (
        select(Deal)
        .where(Deal.status == DealStatus.OPEN)
        .order_by(Deal.amount.desc().nullslast())
        .limit(n)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(d.id),
            "name": d.name,
            "amount": float(d.amount) if d.amount is not None else None,
            "currency": d.currency,
            "expected_close_date": d.expected_close_date.isoformat()
            if d.expected_close_date
            else None,
        }
        for d in rows
    ]


async def _recent_activities(db: AsyncSession, n: int) -> list[dict[str, Any]]:
    stmt = select(Activity).order_by(Activity.created_at.desc()).limit(n)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(a.id),
            "type": a.type.value,
            "target_type": a.target_type.value,
            "target_id": str(a.target_id),
            "subject": a.subject,
            "completed_at": a.completed_at.isoformat() if a.completed_at else None,
            "created_at": a.created_at.isoformat(),
        }
        for a in rows
    ]


async def _counts(db: AsyncSession) -> dict[str, int]:
    contacts = (await db.execute(select(func.count()).select_from(Contact))).scalar_one()
    companies = (await db.execute(select(func.count()).select_from(Company))).scalar_one()
    return {"contacts": int(contacts), "companies": int(companies)}


async def _quotations_summary(db: AsyncSession) -> dict[str, Any]:
    """KPI roll-up over the quotations table. Mirrors QuotationSummary."""
    from datetime import timedelta as _td
    from decimal import Decimal as _D
    from salespilot.models.quotation import Quotation

    now = datetime.now(UTC)
    fourteen = now - _td(days=14)
    thirty = now - _td(days=30)
    ninety = now - _td(days=90)

    rows = (await db.execute(select(Quotation))).scalars().all()
    open_count = 0
    open_amount = _D("0")
    expiring = 0
    expired = 0
    accepted_30d_count = 0
    accepted_30d_amount = _D("0")
    accepted_90d = 0
    rejected_90d = 0
    for q in rows:
        amount = q.amount_gross or q.amount_net or _D("0")
        if q.status == "sent":
            if q.valid_until is None or q.valid_until > now:
                open_count += 1
                open_amount += amount
            if q.sent_at is not None and thirty <= q.sent_at <= fourteen:
                expiring += 1
            if q.valid_until is not None and q.valid_until <= now:
                expired += 1
        elif q.status == "expired":
            expired += 1
        elif q.status == "accepted":
            if q.accepted_at and q.accepted_at >= thirty:
                accepted_30d_count += 1
                accepted_30d_amount += amount
            if q.accepted_at and q.accepted_at >= ninety:
                accepted_90d += 1
        elif q.status == "rejected":
            if q.rejected_at and q.rejected_at >= ninety:
                rejected_90d += 1

    hit_rate = 0.0
    if accepted_90d + rejected_90d > 0:
        hit_rate = round(accepted_90d / (accepted_90d + rejected_90d) * 100, 1)

    return {
        "open_count": open_count,
        "open_amount": str(open_amount),
        "expiring_soon_count": expiring,
        "expired_count": expired,
        "accepted_count_30d": accepted_30d_count,
        "accepted_amount_30d": str(accepted_30d_amount),
        "hit_rate_90d": hit_rate,
        "currency": "EUR",
    }


@router.get("")
async def get_dashboard(db: Db) -> dict[str, Any]:
    now = datetime.now(UTC)
    start_of_this_month = _start_of_month(now)
    thirty_days_ago = now - timedelta(days=30)

    return {
        "generated_at": now.isoformat(),
        "open_pipeline": await _open_pipeline_total(db),
        "won_this_month": await _stats_since(db, DealStatus.WON, start_of_this_month),
        "lost_this_month": await _stats_since(db, DealStatus.LOST, start_of_this_month),
        "won_last_30d": await _stats_since(db, DealStatus.WON, thirty_days_ago),
        "win_rate_90d": await _win_rate_last_n_days(db, 90),
        "deals_per_stage": await _deals_per_stage(db),
        "won_revenue_by_month": await _won_revenue_by_month(db, 6),
        "top_open_deals": await _top_open_deals(db, 5),
        "recent_activities": await _recent_activities(db, 10),
        "totals": await _counts(db),
        "quotations": await _quotations_summary(db),
    }
