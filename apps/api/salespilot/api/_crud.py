"""Generic CRUD helper used by all tenant-scoped resources.

Each tenant-scoped table gets:
    GET    /<resource>?<filters>         list (paginated, filterable)
    POST   /<resource>                    create
    GET    /<resource>/{id}               read
    PATCH  /<resource>/{id}               update
    DELETE /<resource>/{id}               delete

`filterable_fields` is an allow-list of column names that can be filtered
via query string. The list endpoint translates `?company_id=uuid` to
`WHERE company_id = uuid`. We keep the surface narrow on purpose: anything
that isn't on the allow-list is silently ignored so junk query strings
don't leak schema info or accidentally match other columns.
"""

from typing import Any, TypeVar
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
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
    filterable_fields: tuple[str, ...] = (),
) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[tag])

    @router.get("", response_model=Page[public_schema])  # type: ignore[valid-type]
    async def list_items(
        request: Request,
        db: Db,
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> Any:
        stmt = select(model)
        count_stmt = select(func.count()).select_from(model)

        # Apply allow-listed filters from the query string.
        for key in filterable_fields:
            raw = request.query_params.get(key)
            if raw is None or raw == "":
                continue
            col = getattr(model, key)
            stmt = stmt.where(col == raw)
            count_stmt = count_stmt.where(col == raw)

        total = (await db.execute(count_stmt)).scalar_one()
        rows = (
            await db.execute(
                stmt.order_by(model.created_at.desc()).limit(limit).offset(offset)  # type: ignore[attr-defined]
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
