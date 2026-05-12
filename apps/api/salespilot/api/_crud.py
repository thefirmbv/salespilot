"""Generic CRUD helper to avoid four near-identical route files.

Each tenant-scoped table gets standard endpoints:
    GET    /<resource>                 list (paginated)
    POST   /<resource>                 create
    GET    /<resource>/{id}             read
    PATCH  /<resource>/{id}             update
    DELETE /<resource>/{id}             delete

The org_id is set automatically from the tenant session (RLS would block
cross-tenant writes regardless, but we set it explicitly so the row is
visible to the same session).
"""

from typing import Any, TypeVar
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from salespilot.deps import CurrentAuth, Db
from salespilot.models import Base
from salespilot.schemas.crm import Page

ModelT = TypeVar("ModelT", bound=Base)
CreateT = TypeVar("CreateT", bound=BaseModel)
UpdateT = TypeVar("UpdateT", bound=BaseModel)
PublicT = TypeVar("PublicT", bound=BaseModel)


def make_crud_router(
    *,
    prefix: str,
    tag: str,
    model: type[ModelT],
    create_schema: type[CreateT],
    update_schema: type[UpdateT],
    public_schema: type[PublicT],
) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[tag])

    @router.get("", response_model=Page[public_schema])  # type: ignore[valid-type]
    async def list_items(
        db: Db,
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> Any:
        total = (await db.execute(select(func.count()).select_from(model))).scalar_one()
        rows = (
            await db.execute(
                select(model).order_by(model.created_at.desc()).limit(limit).offset(offset)  # type: ignore[attr-defined]
            )
        ).scalars().all()
        return Page[public_schema](  # type: ignore[valid-type]
            items=[public_schema.model_validate(r) for r in rows],  # type: ignore[arg-type]
            total=total,
            limit=limit,
            offset=offset,
        )

    @router.post("", response_model=public_schema, status_code=201)  # type: ignore[valid-type]
    async def create_item(payload: create_schema, db: Db, auth: CurrentAuth) -> Any:  # type: ignore[valid-type]
        data = payload.model_dump(exclude_unset=False)
        # Set org_id from the tenant context. Required even though RLS would
        # also block: SQLAlchemy validates NOT NULL before INSERT.
        data["org_id"] = auth.org_id
        item = model(**data)
        db.add(item)
        await db.flush()
        await db.refresh(item)
        return public_schema.model_validate(item)  # type: ignore[attr-defined]

    @router.get("/{item_id}", response_model=public_schema)  # type: ignore[valid-type]
    async def read_item(item_id: UUID, db: Db) -> Any:
        item = await db.get(model, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail=f"{tag} not found")
        return public_schema.model_validate(item)  # type: ignore[attr-defined]

    @router.patch("/{item_id}", response_model=public_schema)  # type: ignore[valid-type]
    async def update_item(item_id: UUID, payload: update_schema, db: Db) -> Any:  # type: ignore[valid-type]
        item = await db.get(model, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail=f"{tag} not found")
        changes = payload.model_dump(exclude_unset=True)
        for k, v in changes.items():
            setattr(item, k, v)
        await db.flush()
        await db.refresh(item)
        return public_schema.model_validate(item)  # type: ignore[attr-defined]

    @router.delete("/{item_id}", status_code=204)
    async def delete_item(item_id: UUID, db: Db) -> None:
        item = await db.get(model, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail=f"{tag} not found")
        await db.delete(item)
        await db.flush()

    return router
