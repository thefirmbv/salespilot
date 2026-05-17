"""Access-management API.

Endpoints:
    GET  /access/me                -- current user's groups + visible sections
    GET  /access/users             -- list users + their groups (admin only)
    PUT  /access/users/{id}/groups -- replace a user's groups (admin only)
    GET  /access/sections          -- catalog of all known sections + groups

Group changes are immediate. Frontend re-fetches /access/me after each
mutation so the sidebar refreshes.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from salespilot.access import (
    KNOWN_GROUPS, SECTIONS,
    require_groups, visible_sections,
)
from salespilot.deps import CurrentAuth, DbNoTenant
from salespilot.models.auth import OrgMembership, User


router = APIRouter(prefix="/access", tags=["access"])


# ----------------------------------------------------------------------
# /access/me
# ----------------------------------------------------------------------


class MeResponse(BaseModel):
    user_id: UUID
    email: str
    org_id: UUID | None
    groups: list[str]
    is_admin: bool
    visible_sections: list[str]


@router.get("/me", response_model=MeResponse)
async def get_me(auth: CurrentAuth, db: DbNoTenant) -> MeResponse:
    """Light read-after-login: tells the frontend who's logged in,
    which groups they have, and which sidebar sections to show."""
    u = (
        await db.execute(select(User).where(User.id == auth.user_id))
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="User niet gevonden")
    return MeResponse(
        user_id=u.id,
        email=u.email,
        org_id=auth.org_id,
        groups=list(auth.groups),
        is_admin="administrators" in auth.groups,
        visible_sections=visible_sections(auth.groups),
    )


# ----------------------------------------------------------------------
# /access/sections (catalog)
# ----------------------------------------------------------------------


class SectionCatalogEntry(BaseModel):
    id: str
    label: str
    allowed_groups: list[str]
    routes: list[str]


class SectionsCatalog(BaseModel):
    sections: list[SectionCatalogEntry]
    known_groups: list[str]


@router.get("/sections", response_model=SectionsCatalog)
async def list_sections() -> SectionsCatalog:
    """Public catalog of all sections + groups. Used by the access-
    management UI to render checkboxes. Doesn't leak any user data."""
    out: list[SectionCatalogEntry] = []
    for sid, sec in SECTIONS.items():
        out.append(SectionCatalogEntry(
            id=sid,
            label=sec["label"],
            allowed_groups=sorted(sec["allowed_groups"]),
            routes=sec["routes"],
        ))
    return SectionsCatalog(sections=out, known_groups=list(KNOWN_GROUPS))


# ----------------------------------------------------------------------
# /access/users (admin only)
# ----------------------------------------------------------------------


class UserRow(BaseModel):
    user_id: UUID
    email: str
    is_platform_admin: bool
    groups: list[str]


@router.get("/users", response_model=list[UserRow])
async def list_users(auth: CurrentAuth, db: DbNoTenant) -> list[UserRow]:
    require_groups("administrators")(auth)
    if auth.org_id is None:
        raise HTTPException(status_code=400, detail="Geen actieve organisatie.")
    rows = (
        await db.execute(
            select(User, OrgMembership)
            .join(OrgMembership, OrgMembership.user_id == User.id)
            .where(OrgMembership.org_id == auth.org_id)
            .order_by(User.email)
        )
    ).all()
    return [
        UserRow(
            user_id=u.id,
            email=u.email,
            is_platform_admin=u.is_platform_admin,
            groups=list(m.groups or []),
        )
        for u, m in rows
    ]


class UpdateGroupsBody(BaseModel):
    groups: list[str] = Field(..., description="New full set of groups for this user")


@router.put("/users/{user_id}/groups", response_model=UserRow)
async def update_user_groups(
    user_id: UUID,
    body: UpdateGroupsBody,
    auth: CurrentAuth,
    db: DbNoTenant,
) -> UserRow:
    """Replace a user's groups in the current org. Only administrators
    can call this. Unknown group names are silently dropped to avoid
    typos creating dead labels."""
    require_groups("administrators")(auth)
    if auth.org_id is None:
        raise HTTPException(status_code=400, detail="Geen actieve organisatie.")

    # Filter to known groups, preserve order, dedupe.
    seen: set[str] = set()
    cleaned: list[str] = []
    for g in body.groups:
        if g in KNOWN_GROUPS and g not in seen:
            seen.add(g)
            cleaned.append(g)

    # Safety net: never strip administrators from the LAST admin
    # (or you'd lock yourself out). Allow stripping anyone else.
    if "administrators" not in cleaned:
        other_admins = (
            await db.execute(
                select(OrgMembership).where(
                    OrgMembership.org_id == auth.org_id,
                    OrgMembership.user_id != user_id,
                    OrgMembership.groups.contains(["administrators"]),
                )
            )
        ).scalars().all()
        if len(other_admins) == 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Kan 'administrators' niet weghalen van deze gebruiker -- "
                    "er moet minstens 1 administrator overblijven."
                ),
            )

    m = (
        await db.execute(
            select(OrgMembership).where(
                OrgMembership.user_id == user_id,
                OrgMembership.org_id == auth.org_id,
            )
        )
    ).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="Membership niet gevonden")
    m.groups = cleaned
    u = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one()
    await db.commit()
    return UserRow(
        user_id=u.id,
        email=u.email,
        is_platform_admin=u.is_platform_admin,
        groups=cleaned,
    )
