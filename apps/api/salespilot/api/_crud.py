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

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession
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
    searchable_fields: tuple[str, ...] = (),
    sortable_fields: tuple[str, ...] = (),
    default_sort: str = "-created_at",
    on_before_save: "Callable[[Any, AsyncSession], Awaitable[None]] | None" = None,
) -> APIRouter:
    """`on_before_save` is invoked after fields have been applied but before
    the final flush, both on create and on update. Use it for business rules
    that depend on the resulting state of the row (e.g. derive deal.status
    from the chosen stage)."""
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
        # `?field=value` does an equality match.
        # `?field__in=a,b,c` does an IN match (comma-separated).
        for key in filterable_fields:
            col = getattr(model, key)
            raw = request.query_params.get(key)
            if raw not in (None, ""):
                stmt = stmt.where(col == raw)
                count_stmt = count_stmt.where(col == raw)
            raw_in = request.query_params.get(f"{key}__in")
            if raw_in:
                values = [v.strip() for v in raw_in.split(",") if v.strip()]
                if values:
                    stmt = stmt.where(col.in_(values))
                    count_stmt = count_stmt.where(col.in_(values))

        # Free-text search across searchable_fields.
        q = request.query_params.get("q")
        if q and searchable_fields:
            from sqlalchemy import or_
            pattern = f"%{q}%"
            search_clauses = [
                getattr(model, f).ilike(pattern) for f in searchable_fields
            ]
            stmt = stmt.where(or_(*search_clauses))
            count_stmt = count_stmt.where(or_(*search_clauses))

        # Sorting: ?sort=field for ASC, ?sort=-field for DESC. Only allow-listed
        # fields plus the default 'created_at' (since lists default to it).
        sort_param = request.query_params.get("sort", default_sort)
        sort_key = sort_param.lstrip("-")
        sort_desc = sort_param.startswith("-")
        allowed_sorts = set(sortable_fields) | {"created_at"}
        if sort_key not in allowed_sorts:
            sort_key = "created_at"
            sort_desc = True
        sort_col = getattr(model, sort_key)
        stmt = stmt.order_by(sort_col.desc() if sort_desc else sort_col.asc())

        total = (await db.execute(count_stmt)).scalar_one()
        rows = (
            await db.execute(stmt.limit(limit).offset(offset))
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
        # Strip fields that aren't real model columns -- create_schema may
        # include UI-only flags (e.g. auto_followup_on_no_answer) that are
        # handled by the on_before_save hook.
        model_keys = {c.name for c in model.__table__.columns}
        model_data = {k: v for k, v in data.items() if k in model_keys}
        item = model(**model_data)
        # Keep the rest accessible to the hook via __pydantic_extra__-like
        # attribute so on_before_save can inspect 'auto_followup_on_no_answer'.
        for k, v in data.items():
            if k not in model_keys:
                setattr(item, f"_input_{k}", v)
        # Hook can read this to know who created the row
        item._auth_user_id = auth.user_id
        db.add(item)
        if on_before_save is not None:
            await on_before_save(item, db)
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
        model_keys = {c.name for c in model.__table__.columns}
        for k, v in changes.items():
            if k in model_keys:
                setattr(item, k, v)
            else:
                # Pass UI-only flags to the hook via prefixed attrs
                setattr(item, f"_input_{k}", v)
        if on_before_save is not None:
            await on_before_save(item, db)
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
