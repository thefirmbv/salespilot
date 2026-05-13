"""Enriched Activities listing with target name + quotation context.

The default /activities endpoint returns raw rows. This one joins in the
target (company/contact/deal name) so the UI can render rich rows
without N+1 fetches.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from salespilot.deps import CurrentAuth, Db
from salespilot.models.auth import User
from salespilot.models.crm import Activity, ActivityTarget, Company, Contact, Deal
from salespilot.models.quotation import Quotation

router = APIRouter(prefix="/activities-enriched", tags=["activities"])


class ActivityEnriched(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: str
    target_type: str
    target_id: UUID
    target_name: str | None = None
    subject: str | None = None
    body: str | None = None
    due_at: datetime | None = None
    completed_at: datetime | None = None
    quotation_id: UUID | None = None
    quotation_reference: str | None = None
    quotation_amount: str | None = None
    reminder_kind: str | None = None
    is_overdue: bool = False
    # New fields for manual call-followup workflow
    assignee_id: UUID | None = None
    assignee_name: str | None = None
    author_id: UUID | None = None
    author_name: str | None = None
    priority: str = "normal"
    phone_override: str | None = None
    outcome: str | None = None
    outcome_notes: str | None = None
    next_followup_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class ActivitiesSummary(BaseModel):
    overdue_count: int = 0
    today_count: int = 0
    this_week_count: int = 0
    completed_30d_count: int = 0
    open_total: int = 0
    open_followup_count: int = 0  # quote_followup_* still open


def _contact_name(c: Contact | None) -> str | None:
    if c is None:
        return None
    parts = [c.first_name, c.last_name]
    out = " ".join(p for p in parts if p).strip()
    return out or None


@router.get("", response_model=list[ActivityEnriched])
async def list_activities_enriched(
    auth: CurrentAuth,
    db: Db,
    bucket: str | None = Query(None, description="overdue|today|week|done|followup|all"),
    type: str | None = Query(None, description="comma-separated"),
    limit: int = Query(300, le=1000),
) -> list[ActivityEnriched]:
    now = datetime.now(UTC)
    today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    today_end = today_start + timedelta(days=1)
    week_end = today_start + timedelta(days=7)
    thirty = now - timedelta(days=30)

    stmt = select(Activity)
    if bucket == "overdue":
        stmt = stmt.where(
            Activity.completed_at.is_(None),
            Activity.due_at.is_not(None),
            Activity.due_at < now,
        )
    elif bucket == "today":
        stmt = stmt.where(
            Activity.completed_at.is_(None),
            Activity.due_at >= today_start,
            Activity.due_at < today_end,
        )
    elif bucket == "week":
        stmt = stmt.where(
            Activity.completed_at.is_(None),
            Activity.due_at >= today_start,
            Activity.due_at < week_end,
        )
    elif bucket == "done":
        stmt = stmt.where(
            Activity.completed_at.is_not(None),
            Activity.completed_at >= thirty,
        )
    elif bucket == "followup":
        stmt = stmt.where(
            Activity.completed_at.is_(None),
            Activity.reminder_kind.like("quote_followup%"),
        )
    if type:
        types = [t.strip() for t in type.split(",") if t.strip()]
        if types:
            stmt = stmt.where(Activity.type.in_(types))

    # Sort: overdue first (due_at asc), then by due_at asc, then by created desc.
    stmt = stmt.order_by(
        Activity.completed_at.is_not(None).asc(),  # open first
        Activity.due_at.asc().nullslast(),
        Activity.created_at.desc(),
    ).limit(limit)

    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return []

    # Batch lookups by target_type.
    company_ids: set[UUID] = set()
    contact_ids: set[UUID] = set()
    deal_ids: set[UUID] = set()
    for a in rows:
        tt = a.target_type.value if hasattr(a.target_type, "value") else a.target_type
        if tt == "company":
            company_ids.add(a.target_id)
        elif tt == "contact":
            contact_ids.add(a.target_id)
        elif tt == "deal":
            deal_ids.add(a.target_id)

    companies: dict[UUID, Company] = {}
    contacts: dict[UUID, Contact] = {}
    deals: dict[UUID, Deal] = {}
    if company_ids:
        for c in (await db.execute(select(Company).where(Company.id.in_(company_ids)))).scalars():
            companies[c.id] = c
    if contact_ids:
        for c in (await db.execute(select(Contact).where(Contact.id.in_(contact_ids)))).scalars():
            contacts[c.id] = c
    if deal_ids:
        for d in (await db.execute(select(Deal).where(Deal.id.in_(deal_ids)))).scalars():
            deals[d.id] = d

    # Quotation lookup
    quotation_ids = {a.quotation_id for a in rows if a.quotation_id}
    quotations: dict[UUID, Quotation] = {}
    if quotation_ids:
        for q in (await db.execute(select(Quotation).where(Quotation.id.in_(quotation_ids)))).scalars():
            quotations[q.id] = q

    # Author + assignee names (one query for both sets, deduped)
    user_ids: set[UUID] = set()
    for a in rows:
        if a.author_id:
            user_ids.add(a.author_id)
        if a.assignee_id:
            user_ids.add(a.assignee_id)
    users: dict[UUID, User] = {}
    if user_ids:
        for u in (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars():
            users[u.id] = u

    out: list[ActivityEnriched] = []
    for a in rows:
        tt = a.target_type.value if hasattr(a.target_type, "value") else a.target_type
        target_name: str | None = None
        if tt == "company":
            c = companies.get(a.target_id)
            target_name = c.name if c else None
        elif tt == "contact":
            target_name = _contact_name(contacts.get(a.target_id))
        elif tt == "deal":
            d = deals.get(a.target_id)
            target_name = d.name if d else None

        q = quotations.get(a.quotation_id) if a.quotation_id else None
        is_overdue = bool(
            a.completed_at is None and a.due_at is not None and a.due_at < now
        )

        out.append(
            ActivityEnriched(
                id=a.id,
                type=a.type.value if hasattr(a.type, "value") else str(a.type),
                target_type=tt,
                target_id=a.target_id,
                target_name=target_name,
                subject=a.subject,
                body=a.body,
                due_at=a.due_at,
                completed_at=a.completed_at,
                quotation_id=a.quotation_id,
                quotation_reference=q.reference if q else None,
                quotation_amount=(
                    str(q.amount_gross or q.amount_net) if q and (q.amount_gross or q.amount_net) else None
                ),
                reminder_kind=a.reminder_kind,
                is_overdue=is_overdue,
                assignee_id=a.assignee_id,
                assignee_name=(
                    (users[a.assignee_id].full_name or users[a.assignee_id].email)
                    if a.assignee_id and a.assignee_id in users else None
                ),
                author_id=a.author_id,
                author_name=(
                    (users[a.author_id].full_name or users[a.author_id].email)
                    if a.author_id and a.author_id in users else None
                ),
                priority=getattr(a, "priority", None) or "normal",
                phone_override=getattr(a, "phone_override", None),
                outcome=getattr(a, "outcome", None),
                outcome_notes=getattr(a, "outcome_notes", None),
                next_followup_id=getattr(a, "next_followup_id", None),
                created_at=a.created_at,
                updated_at=a.updated_at,
            )
        )
    return out


@router.get("/summary", response_model=ActivitiesSummary)
async def activities_summary(auth: CurrentAuth, db: Db) -> ActivitiesSummary:
    now = datetime.now(UTC)
    today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    today_end = today_start + timedelta(days=1)
    week_end = today_start + timedelta(days=7)
    thirty = now - timedelta(days=30)

    rows = (await db.execute(select(Activity))).scalars().all()
    overdue = 0
    today = 0
    week = 0
    done_30d = 0
    open_total = 0
    followups = 0
    for a in rows:
        if a.completed_at is None:
            open_total += 1
            if a.reminder_kind and a.reminder_kind.startswith("quote_followup"):
                followups += 1
            if a.due_at is not None and a.due_at < now:
                overdue += 1
            if a.due_at is not None and today_start <= a.due_at < today_end:
                today += 1
            if a.due_at is not None and today_start <= a.due_at < week_end:
                week += 1
        else:
            if a.completed_at >= thirty:
                done_30d += 1

    return ActivitiesSummary(
        overdue_count=overdue,
        today_count=today,
        this_week_count=week,
        completed_30d_count=done_30d,
        open_total=open_total,
        open_followup_count=followups,
    )
