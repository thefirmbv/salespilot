"""Auth endpoints: register, login, magic-link, refresh, me.

Register creates a User + an Organization + an OWNER OrgMembership in one
transaction. Login issues an access + refresh token pair. Magic-link sends
an email (or logs to stdout in dev) with a signed token that can be exchanged
for tokens.
"""

from datetime import UTC, datetime
from re import sub as re_sub
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from sqlalchemy import select

from salespilot.config import get_settings
from salespilot.deps import CurrentAuth, Db, DbNoTenant
from salespilot.mail import send_magic_link_email
from salespilot.models.auth import OrgMembership, OrgRole, Organization, User
from salespilot.schemas.auth import (
    LoginRequest,
    MagicLinkRequest,
    MagicLinkVerify,
    MeResponse,
    MembershipPublic,
    OrgPublic,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserPublic,
)
from salespilot.security import (
    TokenError,
    create_access_token,
    create_magic_link_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_magic_link_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _slugify(name: str) -> str:
    s = re_sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "org"


def _issue_pair(user_id, org_id) -> TokenPair:  # type: ignore[no-untyped-def]
    access, exp = create_access_token(user_id, org_id)
    refresh, _ = create_refresh_token(user_id)
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        access_expires_at=exp,
    )


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, db: DbNoTenant) -> TokenPair:
    email = data.email.lower()
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="email already in use")

    # Find a free slug.
    base = _slugify(data.org_name)
    slug = base
    suffix = 0
    while True:
        clash = await db.execute(select(Organization).where(Organization.slug == slug))
        if clash.scalar_one_or_none() is None:
            break
        suffix += 1
        slug = f"{base}-{suffix}"

    org = Organization(id=uuid4(), name=data.org_name, slug=slug)
    user = User(
        id=uuid4(),
        email=email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
    )
    membership = OrgMembership(
        id=uuid4(), user_id=user.id, org_id=org.id, role=OrgRole.OWNER
    )
    db.add_all([org, user, membership])
    await db.flush()
    return _issue_pair(user.id, org.id)


@router.post("/login", response_model=TokenPair)
async def login(data: LoginRequest, db: DbNoTenant) -> TokenPair:
    email = data.email.lower()
    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is None or user.password_hash is None or not verify_password(data.password, user.password_hash):
        # Constant-ish message to avoid email enumeration.
        raise HTTPException(status_code=401, detail="invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="account disabled")

    # First membership is the default active org. Improve later: user pref.
    membership = (
        await db.execute(
            select(OrgMembership).where(OrgMembership.user_id == user.id).limit(1)
        )
    ).scalar_one_or_none()

    user.last_login_at = datetime.now(UTC)
    org_id = membership.org_id if membership else None
    return _issue_pair(user.id, org_id)


@router.post("/magic-link/request", status_code=status.HTTP_202_ACCEPTED)
async def request_magic_link(
    data: MagicLinkRequest, background_tasks: BackgroundTasks, db: DbNoTenant
) -> dict[str, str]:
    """Always returns 202, regardless of whether the email exists.

    This prevents using this endpoint to enumerate users. If the user exists,
    an email is queued in the background; otherwise we silently do nothing.
    """
    email = data.email.lower()
    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is not None and user.is_active:
        token = create_magic_link_token(email)
        settings = get_settings()
        link = f"{str(settings.app_base_url).rstrip('/')}/login/magic?token={token}"
        background_tasks.add_task(send_magic_link_email, email, link)
    return {"status": "ok"}


@router.post("/magic-link/verify", response_model=TokenPair)
async def verify_magic_link(data: MagicLinkVerify, db: DbNoTenant) -> TokenPair:
    try:
        email = verify_magic_link_token(data.token)
    except TokenError as e:
        raise HTTPException(status_code=400, detail=f"magic link {e}") from e

    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=400, detail="user not found")

    membership = (
        await db.execute(
            select(OrgMembership).where(OrgMembership.user_id == user.id).limit(1)
        )
    ).scalar_one_or_none()

    user.last_login_at = datetime.now(UTC)
    org_id = membership.org_id if membership else None
    return _issue_pair(user.id, org_id)


@router.post("/refresh", response_model=TokenPair)
async def refresh(data: RefreshRequest, db: DbNoTenant) -> TokenPair:
    try:
        payload = decode_token(data.refresh_token, "refresh")
    except TokenError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    user_id = payload["sub"]
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="user not found")
    membership = (
        await db.execute(
            select(OrgMembership).where(OrgMembership.user_id == user.id).limit(1)
        )
    ).scalar_one_or_none()
    org_id = membership.org_id if membership else None
    return _issue_pair(user.id, org_id)


@router.get("/me", response_model=MeResponse)
async def me(auth: CurrentAuth, db: Db) -> MeResponse:
    user = await db.get(User, auth.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    memberships_raw = (
        await db.execute(
            select(OrgMembership, Organization)
            .join(Organization, Organization.id == OrgMembership.org_id)
            .where(OrgMembership.user_id == auth.user_id)
        )
    ).all()
    memberships = [
        MembershipPublic(org=OrgPublic.model_validate(o), role=m.role.value)
        for m, o in memberships_raw
    ]

    current_org = None
    if auth.org_id is not None:
        org = await db.get(Organization, auth.org_id)
        if org is not None:
            current_org = OrgPublic.model_validate(org)

    return MeResponse(
        user=UserPublic.model_validate(user),
        current_org=current_org,
        memberships=memberships,
    )
