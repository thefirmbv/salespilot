"""FastAPI dependencies: current_user, current_org, db sessions.

The Authorization header carries a JWT access token. Its payload contains the
user_id (sub) and the active org_id (org). Routes that require a tenant
context use `TenantSession` which yields an AsyncSession with the
`app.current_org_id` GUC set to the user's active org.
"""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from salespilot.db import raw_session, tenant_session
from salespilot.models.auth import OrgMembership, Organization, User
from salespilot.security import TokenError, decode_token


def _extract_bearer(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing authorization"
        )
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid authorization header"
        )
    return parts[1]


class AuthContext:
    """Decoded JWT context attached to the request."""

    def __init__(self, user_id: UUID, org_id: UUID | None) -> None:
        self.user_id = user_id
        self.org_id = org_id


async def get_auth_context(
    authorization: Annotated[str | None, Header()] = None,
) -> AuthContext:
    token = _extract_bearer(authorization)
    try:
        payload = decode_token(token, "access")
    except TokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)
        ) from e
    user_id = UUID(payload["sub"])
    org_id = UUID(payload["org"]) if payload.get("org") else None
    return AuthContext(user_id=user_id, org_id=org_id)


CurrentAuth = Annotated[AuthContext, Depends(get_auth_context)]


async def get_db_no_tenant() -> AsyncIterator[AsyncSession]:
    """Session without tenant scope. Use only on /auth endpoints."""
    async with raw_session() as session:
        yield session


DbNoTenant = Annotated[AsyncSession, Depends(get_db_no_tenant)]


async def get_db(auth: CurrentAuth) -> AsyncIterator[AsyncSession]:
    """Tenant-scoped session. Requires an org in the JWT."""
    if auth.org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no active organization on this token",
        )
    async with tenant_session(auth.org_id) as session:
        yield session


Db = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(auth: CurrentAuth, db: Db) -> User:
    """Load and return the User row for the JWT's `sub` claim."""
    user = await db.get(User, auth.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found or inactive"
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_membership(auth: CurrentAuth, db: Db) -> OrgMembership:
    """Verify the user is actually a member of the active org."""
    stmt = select(OrgMembership).where(
        OrgMembership.user_id == auth.user_id,
        OrgMembership.org_id == auth.org_id,
    )
    result = await db.execute(stmt)
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not a member of this organization",
        )
    return membership


CurrentMembership = Annotated[OrgMembership, Depends(get_current_membership)]


async def get_current_org(membership: CurrentMembership, db: Db) -> Organization:
    org = await db.get(Organization, membership.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="organization not found")
    return org


CurrentOrg = Annotated[Organization, Depends(get_current_org)]
