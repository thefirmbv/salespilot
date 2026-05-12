"""Pipelines & stages — read-only listing for now.

Used by the frontend's Deal form to populate pipeline / stage dropdowns.
Full CRUD comes later when we build a pipeline-management page.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select

from salespilot.deps import Db
from salespilot.models.crm import Pipeline, Stage

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


@router.get("")
async def list_pipelines(db: Db) -> list[dict[str, Any]]:
    rows = (
        await db.execute(select(Pipeline).order_by(Pipeline.name))
    ).scalars().all()
    return [
        {"id": str(p.id), "name": p.name, "is_default": p.is_default}
        for p in rows
    ]


@router.get("/{pipeline_id}/stages")
async def list_stages(pipeline_id: UUID, db: Db) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(Stage)
            .where(Stage.pipeline_id == pipeline_id)
            .order_by(Stage.position)
        )
    ).scalars().all()
    return [
        {
            "id": str(s.id),
            "name": s.name,
            "position": s.position,
            "probability": s.probability,
            "is_won": s.is_won,
            "is_lost": s.is_lost,
        }
        for s in rows
    ]
