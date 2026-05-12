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

activities_router = make_crud_router(
    prefix="/activities",
    tag="activities",
    model=Activity,
    create_schema=ActivityCreate,
    update_schema=ActivityUpdate,
    public_schema=ActivityPublic,
    filterable_fields=("target_type", "target_id", "type", "author_id"),
    searchable_fields=("subject", "body"),
    sortable_fields=("type", "subject", "due_at", "completed_at", "updated_at"),
)
