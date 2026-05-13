"""Mount CRUD routers for the standard CRM objects."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from salespilot.api._crud import make_crud_router
from salespilot.models.crm import Activity, Company, Contact, Deal, DealStatus, Stage
from salespilot.schemas.crm import (
    ActivityCreate,
    ActivityPublic,
    ActivityUpdate,
    CompanyCreate,
    CompanyPublic,
    CompanyUpdate,
    ContactCreate,
    ContactPublic,
    ContactUpdate,
    DealCreate,
    DealPublic,
    DealUpdate,
)


async def _deal_before_save(item: Any, db: AsyncSession) -> None:
    """Keep deal.status in sync with stage.is_won / is_lost.

    Moving a deal to a 'won' stage marks it won and stamps closed_at.
    Moving to a 'lost' stage marks it lost. Moving to any other stage
    reopens the deal (status=open, closed_at cleared).
    """
    if not isinstance(item, Deal):
        return
    stage = await db.get(Stage, item.stage_id)
    if stage is None:
        return
    now = datetime.now(UTC)
    if stage.is_won:
        item.status = DealStatus.WON
        if item.closed_at is None:
            item.closed_at = now
    elif stage.is_lost:
        item.status = DealStatus.LOST
        if item.closed_at is None:
            item.closed_at = now
    else:
        item.status = DealStatus.OPEN
        item.closed_at = None


companies_router = make_crud_router(
    prefix="/companies",
    tag="companies",
    model=Company,
    create_schema=CompanyCreate,
    update_schema=CompanyUpdate,
    public_schema=CompanyPublic,
    filterable_fields=("source", "mail_platform"),
    searchable_fields=("name", "domain", "industry", "description"),
    sortable_fields=("name", "lead_score", "last_visit_at", "pageview_count_30d", "updated_at"),
    default_sort="-lead_score",
)

contacts_router = make_crud_router(
    prefix="/contacts",
    tag="contacts",
    model=Contact,
    create_schema=ContactCreate,
    update_schema=ContactUpdate,
    public_schema=ContactPublic,
    filterable_fields=("company_id", "owner_id"),
    searchable_fields=("first_name", "last_name", "email", "phone", "job_title"),
    sortable_fields=("first_name", "last_name", "email", "updated_at"),
)

deals_router = make_crud_router(
    prefix="/deals",
    tag="deals",
    model=Deal,
    create_schema=DealCreate,
    update_schema=DealUpdate,
    public_schema=DealPublic,
    filterable_fields=("company_id", "primary_contact_id", "owner_id", "status", "stage_id"),
    on_before_save=_deal_before_save,
    searchable_fields=("name",),
    sortable_fields=("name", "amount", "expected_close_date", "status", "closed_at", "updated_at"),
)

async def _activity_before_save(item: Any, db: AsyncSession) -> None:
    """Activity-specific business rules:
      * Stamp author_id on first create (we don't overwrite on edit so the
        original creator stays attributed even if someone else edits later).
      * If outcome was just set to 'no_answer' AND the user requested an
        auto follow-up, create a child Activity 2 days later assigned to
        the same person, then link via next_followup_id.
      * If the activity has no assignee, default to the author.
    """
    from uuid import uuid4
    from datetime import timedelta
    if not isinstance(item, Activity):
        return

    auth_user_id = getattr(item, "_auth_user_id", None)
    if item.author_id is None and auth_user_id is not None:
        item.author_id = auth_user_id
    if item.assignee_id is None:
        item.assignee_id = item.author_id

    # Auto-followup on no_answer. The flag arrives via the UI-only
    # ActivityCreate/Update field; _crud stashes it as `_input_...`.
    wants_followup = bool(
        getattr(item, "_input_auto_followup_on_no_answer", False)
    )
    if (
        wants_followup
        and item.outcome == "no_answer"
        and item.next_followup_id is None
    ):
        now = datetime.now(UTC)
        # Default: same time of day, 2 days later
        followup_due = (item.due_at or now) + timedelta(days=2)
        child = Activity(
            id=uuid4(),
            org_id=item.org_id,
            type=item.type,
            target_type=item.target_type,
            target_id=item.target_id,
            subject=(f"Follow-up: {item.subject}" if item.subject else "Follow-up bel"),
            body=item.outcome_notes,
            due_at=followup_due,
            assignee_id=item.assignee_id,
            author_id=item.author_id,
            priority=item.priority,
            phone_override=item.phone_override,
            quotation_id=item.quotation_id,
            reminder_kind="auto_no_answer_followup",
            created_at=now,
            updated_at=now,
        )
        db.add(child)
        await db.flush()
        item.next_followup_id = child.id


activities_router = make_crud_router(
    prefix="/activities",
    tag="activities",
    model=Activity,
    create_schema=ActivityCreate,
    update_schema=ActivityUpdate,
    public_schema=ActivityPublic,
    filterable_fields=("target_type", "target_id", "type", "author_id", "assignee_id", "priority", "outcome"),
    searchable_fields=("subject", "body"),
    sortable_fields=("type", "subject", "due_at", "completed_at", "updated_at", "priority"),
    on_before_save=_activity_before_save,
)
