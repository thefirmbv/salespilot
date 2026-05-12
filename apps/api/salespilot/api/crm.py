"""Mount CRUD routers for the standard CRM objects."""

from salespilot.api._crud import make_crud_router
from salespilot.models.crm import Activity, Company, Contact, Deal
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

companies_router = make_crud_router(
    prefix="/companies",
    tag="companies",
    model=Company,
    create_schema=CompanyCreate,
    update_schema=CompanyUpdate,
    public_schema=CompanyPublic,
)

contacts_router = make_crud_router(
    prefix="/contacts",
    tag="contacts",
    model=Contact,
    create_schema=ContactCreate,
    update_schema=ContactUpdate,
    public_schema=ContactPublic,
)

deals_router = make_crud_router(
    prefix="/deals",
    tag="deals",
    model=Deal,
    create_schema=DealCreate,
    update_schema=DealUpdate,
    public_schema=DealPublic,
)

activities_router = make_crud_router(
    prefix="/activities",
    tag="activities",
    model=Activity,
    create_schema=ActivityCreate,
    update_schema=ActivityPublic,  # update schema differs less; keep simple here
    public_schema=ActivityPublic,
)
