"""API: Quotations list, summary, manual deal-link, and HaloPSA sync trigger."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from salespilot.deps import CurrentAuth, Db
from salespilot.integrations.halopsa import (
    HaloPSAClient,
    HaloPSACredentials,
    HaloPSAError,
)
from salespilot.integrations.halopsa_quotations import sync_quotations_for_org
from salespilot.models.crm import Company, Deal
from salespilot.models.integrations import Integration
from salespilot.models.quotation import Quotation
from salespilot.schemas.quotation import (
    QuotationPublic,
    QuotationSummary,
    QuotationSyncResult,
)

router = APIRouter(prefix="/quotations", tags=["quotations"])


def _halopsa_creds(row: Integration) -> HaloPSACredentials:
    cfg = row.config_json or {}
    return HaloPSACredentials(
        base_url=cfg.get("base_url", ""),
        client_id=cfg.get("client_id", ""),
        client_secret=cfg.get("client_secret", ""),
        tenant=cfg.get("tenant"),
        scopes=cfg.get("scopes") or "all",
    )


async def _enrich_one(db: AsyncSession, q: Quotation) -> QuotationPublic:
    """Join in company + deal names for display."""
    company = await db.get(Company, q.company_id)
    deal = await db.get(Deal, q.deal_id) if q.deal_id else None
    p = QuotationPublic.model_validate(q)
    p.company_name = company.name if company else None
    p.deal_name = deal.name if deal else None
    return p


@router.get("", response_model=list[QuotationPublic])
async def list_quotations(
    auth: CurrentAuth,
    db: Db,
    status: str | None = Query(None, description="comma-separated statuses"),
    bucket: str | None = Query(None, description="open|expiring|expired|accepted|rejected"),
    company_id: UUID | None = None,
    deal_id: UUID | None = None,
    limit: int = Query(200, le=500),
) -> list[QuotationPublic]:
    stmt = select(Quotation)
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            stmt = stmt.where(Quotation.status.in_(statuses))
    if company_id:
        stmt = stmt.where(Quotation.company_id == company_id)
    if deal_id:
        stmt = stmt.where(Quotation.deal_id == deal_id)
    if bucket:
        now = datetime.now(UTC)
        if bucket == "open":
            # status sent, not yet expired
            stmt = stmt.where(
                Quotation.status == "sent",
                or_(
                    Quotation.valid_until.is_(None),
                    Quotation.valid_until > now,
                ),
            )
        elif bucket == "expiring":
            # status sent, 14-30 days since sent_at
            fourteen = now - timedelta(days=14)
            thirty = now - timedelta(days=30)
            stmt = stmt.where(
                Quotation.status == "sent",
                Quotation.sent_at.is_not(None),
                Quotation.sent_at <= fourteen,
                Quotation.sent_at >= thirty,
            )
        elif bucket == "expired":
            stmt = stmt.where(
                or_(
                    Quotation.status == "expired",
                    and_(
                        Quotation.status == "sent",
                        Quotation.valid_until.is_not(None),
                        Quotation.valid_until <= now,
                    ),
                )
            )
        elif bucket == "accepted":
            stmt = stmt.where(Quotation.status == "accepted")
        elif bucket == "rejected":
            stmt = stmt.where(Quotation.status == "rejected")

    # Order depends on bucket: for active buckets (sent/expiring/expired)
    # the user wants the longest-outstanding offer at the top so it can be
    # followed up first. For closed buckets (accepted/rejected) the most
    # recent decision is most relevant. "All" defaults to oldest-first
    # because the list is primarily a follow-up tool.
    if bucket in ("accepted", "rejected"):
        stmt = stmt.order_by(
            Quotation.sent_at.desc().nullslast(), Quotation.updated_at.desc()
        ).limit(limit)
    else:
        stmt = stmt.order_by(
            Quotation.sent_at.asc().nullsfirst(), Quotation.updated_at.asc()
        ).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [await _enrich_one(db, q) for q in rows]


@router.get("/summary", response_model=QuotationSummary)
async def quotations_summary(auth: CurrentAuth, db: Db) -> QuotationSummary:
    now = datetime.now(UTC)
    fourteen = now - timedelta(days=14)
    thirty = now - timedelta(days=30)
    ninety = now - timedelta(days=90)

    rows = (await db.execute(select(Quotation))).scalars().all()
    open_count = 0
    open_amount = Decimal("0")
    expiring_count = 0
    expired_count = 0
    accepted_30d_count = 0
    accepted_30d_amount = Decimal("0")
    rejected_30d_count = 0
    accepted_90d = 0
    rejected_90d = 0

    for q in rows:
        amount = q.amount_gross or q.amount_net or Decimal("0")

        if q.status == "sent":
            if q.valid_until is None or q.valid_until > now:
                open_count += 1
                open_amount += amount
            if q.sent_at is not None and thirty <= q.sent_at <= fourteen:
                expiring_count += 1
            if q.valid_until is not None and q.valid_until <= now:
                expired_count += 1
        elif q.status == "expired":
            expired_count += 1
        elif q.status == "accepted":
            if q.accepted_at is not None and q.accepted_at >= thirty:
                accepted_30d_count += 1
                accepted_30d_amount += amount
            if q.accepted_at is not None and q.accepted_at >= ninety:
                accepted_90d += 1
        elif q.status == "rejected":
            if q.rejected_at is not None and q.rejected_at >= thirty:
                rejected_30d_count += 1
            if q.rejected_at is not None and q.rejected_at >= ninety:
                rejected_90d += 1

    hit_rate = 0.0
    if accepted_90d + rejected_90d > 0:
        hit_rate = round(accepted_90d / (accepted_90d + rejected_90d) * 100, 1)

    return QuotationSummary(
        open_count=open_count,
        open_amount=open_amount,
        expiring_soon_count=expiring_count,
        expired_count=expired_count,
        accepted_count_30d=accepted_30d_count,
        accepted_amount_30d=accepted_30d_amount,
        rejected_count_30d=rejected_30d_count,
        hit_rate_90d=hit_rate,
    )


@router.get("/{quotation_id}", response_model=QuotationPublic)
async def get_quotation(quotation_id: UUID, auth: CurrentAuth, db: Db) -> QuotationPublic:
    q = await db.get(Quotation, quotation_id)
    if q is None:
        raise HTTPException(status_code=404, detail="quotation not found")
    return await _enrich_one(db, q)


@router.patch("/{quotation_id}/link-deal", response_model=QuotationPublic)
async def link_quotation_to_deal(
    quotation_id: UUID, deal_id: UUID | None, auth: CurrentAuth, db: Db
) -> QuotationPublic:
    q = await db.get(Quotation, quotation_id)
    if q is None:
        raise HTTPException(status_code=404, detail="quotation not found")
    if deal_id is not None:
        deal = await db.get(Deal, deal_id)
        if deal is None:
            raise HTTPException(status_code=404, detail="deal not found")
        if deal.company_id != q.company_id:
            raise HTTPException(
                status_code=400, detail="deal belongs to a different company"
            )
        q.deal_id = deal_id
    else:
        q.deal_id = None
    await db.flush()
    return await _enrich_one(db, q)


@router.post("/sync", response_model=QuotationSyncResult)
async def sync_quotations(auth: CurrentAuth, db: Db) -> QuotationSyncResult:
    """Trigger a full quotations sync from HaloPSA."""
    integ = (
        await db.execute(select(Integration).where(Integration.kind == "halopsa"))
    ).scalar_one_or_none()
    if integ is None or not integ.is_enabled:
        raise HTTPException(status_code=400, detail="HaloPSA not configured or disabled")
    try:
        async with HaloPSAClient(_halopsa_creds(integ)) as client:
            counters = await sync_quotations_for_org(
                db, org_id=auth.org_id, halopsa_client=client
            )
    except HaloPSAError as e:
        return QuotationSyncResult(ok=False, detail=str(e))
    return QuotationSyncResult(
        ok=True,
        detail=(
            f"Synced {counters['fetched']} quotations "
            f"({counters['created']} new, {counters['updated']} updated, "
            f"{counters['deals_created']} new deals, "
            f"{counters['reminders_scheduled']} reminders scheduled)"
        ),
        fetched=counters["fetched"],
        created=counters["created"],
        updated=counters["updated"],
        deals_created=counters["deals_created"],
        reminders_scheduled=counters["reminders_scheduled"],
    )
