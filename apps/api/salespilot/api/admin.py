"""Management dashboard API.

Two access levels:
  * platform_admin = founder/super-admin: sees ALL organizations and ALL
    users, can create orgs + invite users into any org.
  * org_owner / org_admin: sees only their own org + its users, can invite
    new users into their org.

Endpoints:
  GET    /admin/organizations           list orgs (platform-admin only)
  POST   /admin/organizations           create org (platform-admin only)
  GET    /admin/organizations/{id}      org detail with member count
  GET    /admin/users                   list users (filtered by access level)
  POST   /admin/users                   invite a user
  PATCH  /admin/users/{id}              update full_name / is_active
  POST   /admin/users/{id}/memberships  add user to an org with a role
  PATCH  /admin/users/{id}/memberships/{org_id}  change role
  DELETE /admin/users/{id}/memberships/{org_id}  remove from org
  POST   /admin/users/{id}/reset-password         send fresh invite token
  GET    /admin/me                                me + my platform privileges
"""

from datetime import UTC, datetime
from secrets import token_urlsafe
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import func, select

from salespilot.deps import CurrentAuth, Db
from salespilot.models.auth import Organization, OrgMembership, OrgRole, User
from salespilot.security import hash_password


router = APIRouter(prefix="/admin", tags=["admin"])


# ----- Schemas -----


class OrgPublicAdmin(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    slug: str
    logo_url: str | None = None
    brand_color: str | None = None
    created_at: datetime
    updated_at: datetime
    member_count: int = 0


class OrgCreate(BaseModel):
    name: str
    slug: str


class OrgUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None


class MembershipPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    org_id: UUID
    org_name: str | None = None
    role: str


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    full_name: str | None = None
    is_active: bool
    is_platform_admin: bool
    last_login_at: datetime | None = None
    invited_at: datetime | None = None
    has_password: bool = False
    has_pending_invite: bool = False
    created_at: datetime
    memberships: list[MembershipPublic] = []


class UserInvite(BaseModel):
    email: EmailStr
    full_name: str | None = None
    org_id: UUID | None = None  # required for non-platform-admins, who can only invite to their own org
    role: str = "member"  # owner/admin/member/viewer
    is_platform_admin: bool = False  # platform-admin only field


class UserUpdate(BaseModel):
    full_name: str | None = None
    is_active: bool | None = None
    is_platform_admin: bool | None = None


class MembershipUpsert(BaseModel):
    org_id: UUID
    role: str


class MembershipRoleUpdate(BaseModel):
    role: str


class InviteResult(BaseModel):
    ok: bool
    user_id: UUID
    invite_url: str | None = None
    detail: str


class MeAdmin(BaseModel):
    user_id: UUID
    email: str
    full_name: str | None = None
    is_platform_admin: bool
    org_id: UUID
    org_role: str


# ----- Access-control helpers -----


async def _require_platform_admin(db: Db, auth: CurrentAuth) -> User:
    me = await db.get(User, auth.user_id)
    if me is None or not me.is_platform_admin:
        raise HTTPException(status_code=403, detail="platform admin required")
    return me


async def _require_org_admin(db: Db, auth: CurrentAuth, org_id: UUID) -> User:
    """User must be platform admin OR have role owner/admin in this org."""
    me = await db.get(User, auth.user_id)
    if me is None:
        raise HTTPException(status_code=401)
    if me.is_platform_admin:
        return me
    m = (
        await db.execute(
            select(OrgMembership).where(
                OrgMembership.user_id == me.id,
                OrgMembership.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if m is None or m.role not in (OrgRole.OWNER, OrgRole.ADMIN):
        raise HTTPException(
            status_code=403,
            detail="org admin/owner required",
        )
    return me


def _role_enum(s: str) -> OrgRole:
    try:
        return OrgRole(s)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid role: {s}")


# ----- /admin/me -----


@router.get("/me", response_model=MeAdmin)
async def me(auth: CurrentAuth, db: Db) -> MeAdmin:
    user = await db.get(User, auth.user_id)
    if user is None:
        raise HTTPException(status_code=401)
    m = (
        await db.execute(
            select(OrgMembership).where(
                OrgMembership.user_id == user.id,
                OrgMembership.org_id == auth.org_id,
            )
        )
    ).scalar_one_or_none()
    return MeAdmin(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_platform_admin=user.is_platform_admin,
        org_id=auth.org_id,
        org_role=m.role.value if m else "viewer",
    )


# ----- Organizations -----


async def _enrich_org(db: Db, o: Organization) -> OrgPublicAdmin:
    count = (
        await db.execute(
            select(func.count(OrgMembership.id)).where(OrgMembership.org_id == o.id)
        )
    ).scalar() or 0
    p = OrgPublicAdmin.model_validate(o)
    p.member_count = count
    return p


@router.get("/organizations", response_model=list[OrgPublicAdmin])
async def list_orgs(auth: CurrentAuth, db: Db) -> list[OrgPublicAdmin]:
    me = await db.get(User, auth.user_id)
    if me is None:
        raise HTTPException(status_code=401)
    if me.is_platform_admin:
        rows = (await db.execute(select(Organization).order_by(Organization.name))).scalars().all()
    else:
        # Only orgs I'm a member of
        mids = (
            await db.execute(
                select(OrgMembership.org_id).where(OrgMembership.user_id == me.id)
            )
        ).scalars().all()
        rows = (
            await db.execute(
                select(Organization).where(Organization.id.in_(mids)).order_by(Organization.name)
            )
        ).scalars().all()
    return [await _enrich_org(db, o) for o in rows]


@router.post("/organizations", response_model=OrgPublicAdmin, status_code=201)
async def create_org(data: OrgCreate, auth: CurrentAuth, db: Db) -> OrgPublicAdmin:
    await _require_platform_admin(db, auth)
    # Slug must be unique
    existing = (
        await db.execute(select(Organization).where(Organization.slug == data.slug))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="slug already in use")
    now = datetime.now(UTC)
    o = Organization(
        id=uuid4(), name=data.name, slug=data.slug,
        created_at=now, updated_at=now,
    )
    db.add(o)
    await db.flush()
    return await _enrich_org(db, o)


@router.patch("/organizations/{org_id}", response_model=OrgPublicAdmin)
async def update_org(
    org_id: UUID, data: OrgUpdate, auth: CurrentAuth, db: Db
) -> OrgPublicAdmin:
    await _require_org_admin(db, auth, org_id)
    o = await db.get(Organization, org_id)
    if o is None:
        raise HTTPException(status_code=404)
    if data.name is not None:
        o.name = data.name
    if data.slug is not None and data.slug != o.slug:
        # Check uniqueness
        existing = (
            await db.execute(select(Organization).where(Organization.slug == data.slug))
        ).scalar_one_or_none()
        if existing is not None and existing.id != o.id:
            raise HTTPException(status_code=409, detail="slug already in use")
        o.slug = data.slug
    await db.flush()
    return await _enrich_org(db, o)


# ----- Users -----


async def _enrich_user(db: Db, u: User) -> UserPublic:
    # Build manually so we don't trigger lazy-loading of u.memberships,
    # which is a relationship attribute and would crash under async.
    p = UserPublic(
        id=u.id,
        email=u.email,
        full_name=u.full_name,
        is_active=u.is_active,
        is_platform_admin=u.is_platform_admin,
        last_login_at=u.last_login_at,
        invited_at=u.invited_at,
        has_password=bool(u.password_hash),
        has_pending_invite=bool(u.invite_token) and not u.password_hash,
        created_at=u.created_at,
        memberships=[],
    )
    rows = (
        await db.execute(
            select(OrgMembership, Organization)
            .join(Organization, Organization.id == OrgMembership.org_id)
            .where(OrgMembership.user_id == u.id)
        )
    ).all()
    p.memberships = [
        MembershipPublic(
            id=m.id, org_id=m.org_id, org_name=o.name, role=m.role.value,
        )
        for m, o in rows
    ]
    return p


@router.get("/users", response_model=list[UserPublic])
async def list_users(auth: CurrentAuth, db: Db) -> list[UserPublic]:
    me = await db.get(User, auth.user_id)
    if me is None:
        raise HTTPException(status_code=401)
    if me.is_platform_admin:
        rows = (
            await db.execute(select(User).order_by(User.email))
        ).scalars().all()
    else:
        # Org admin/owner: users that share at least one org with me
        my_orgs = (
            await db.execute(
                select(OrgMembership.org_id).where(OrgMembership.user_id == me.id)
            )
        ).scalars().all()
        if not my_orgs:
            return []
        user_ids = (
            await db.execute(
                select(OrgMembership.user_id).where(OrgMembership.org_id.in_(my_orgs))
            )
        ).scalars().all()
        rows = (
            await db.execute(
                select(User).where(User.id.in_(set(user_ids))).order_by(User.email)
            )
        ).scalars().all()
    return [await _enrich_user(db, u) for u in rows]


@router.post("/users", response_model=InviteResult, status_code=201)
async def invite_user(data: UserInvite, auth: CurrentAuth, db: Db) -> InviteResult:
    me = await db.get(User, auth.user_id)
    if me is None:
        raise HTTPException(status_code=401)

    # Determine which org we're inviting to. Platform admin may target any
    # org; org-admin can only invite to orgs they admin.
    target_org_id = data.org_id or auth.org_id
    if not me.is_platform_admin:
        await _require_org_admin(db, auth, target_org_id)
        # Org-admins can't promote to platform admin.
        if data.is_platform_admin:
            raise HTTPException(
                status_code=403, detail="only platform admins can grant platform-admin"
            )

    org = await db.get(Organization, target_org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="organization not found")

    # If a user with this email already exists, add a new membership.
    existing = (
        await db.execute(select(User).where(User.email == data.email))
    ).scalar_one_or_none()
    now = datetime.now(UTC)

    if existing is not None:
        user = existing
        # Already in this org? Then this is a no-op other than role change.
        m = (
            await db.execute(
                select(OrgMembership).where(
                    OrgMembership.user_id == user.id,
                    OrgMembership.org_id == target_org_id,
                )
            )
        ).scalar_one_or_none()
        if m is None:
            db.add(
                OrgMembership(
                    id=uuid4(),
                    user_id=user.id,
                    org_id=target_org_id,
                    role=_role_enum(data.role),
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            m.role = _role_enum(data.role)
        if data.is_platform_admin and me.is_platform_admin:
            user.is_platform_admin = True
        await db.flush()
        return InviteResult(
            ok=True, user_id=user.id, invite_url=None,
            detail=f"Bestaande gebruiker toegevoegd aan {org.name} als {data.role}",
        )

    # Brand new user: create with invite token, no password.
    invite_token = token_urlsafe(32)
    user = User(
        id=uuid4(),
        email=data.email,
        full_name=data.full_name,
        is_active=True,
        is_platform_admin=bool(data.is_platform_admin and me.is_platform_admin),
        invited_at=now,
        invited_by=me.id,
        invite_token=invite_token,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    await db.flush()
    db.add(
        OrgMembership(
            id=uuid4(),
            user_id=user.id,
            org_id=target_org_id,
            role=_role_enum(data.role),
            created_at=now,
            updated_at=now,
        )
    )
    await db.flush()
    invite_url = f"/accept-invite?token={invite_token}"
    return InviteResult(
        ok=True, user_id=user.id, invite_url=invite_url,
        detail=f"Uitnodiging aangemaakt voor {data.email}. Stuur deze link.",
    )


@router.patch("/users/{user_id}", response_model=UserPublic)
async def update_user(
    user_id: UUID, data: UserUpdate, auth: CurrentAuth, db: Db
) -> UserPublic:
    me = await db.get(User, auth.user_id)
    if me is None:
        raise HTTPException(status_code=401)
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404)
    # Platform admin can edit anyone. Org admin can only edit users that
    # share an org with them, and cannot grant platform-admin.
    if not me.is_platform_admin:
        shared = (
            await db.execute(
                select(OrgMembership).where(
                    OrgMembership.user_id == target.id,
                    OrgMembership.org_id.in_(
                        select(OrgMembership.org_id).where(
                            OrgMembership.user_id == me.id,
                            OrgMembership.role.in_([OrgRole.OWNER, OrgRole.ADMIN]),
                        )
                    ),
                )
            )
        ).first()
        if shared is None:
            raise HTTPException(status_code=403)
        if data.is_platform_admin is not None:
            raise HTTPException(status_code=403, detail="only platform admin")
    if data.full_name is not None:
        target.full_name = data.full_name
    if data.is_active is not None:
        target.is_active = data.is_active
    if data.is_platform_admin is not None:
        target.is_platform_admin = data.is_platform_admin
    await db.flush()
    return await _enrich_user(db, target)


@router.post("/users/{user_id}/memberships", response_model=UserPublic)
async def add_membership(
    user_id: UUID, data: MembershipUpsert, auth: CurrentAuth, db: Db
) -> UserPublic:
    await _require_org_admin(db, auth, data.org_id)
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404)
    existing = (
        await db.execute(
            select(OrgMembership).where(
                OrgMembership.user_id == user.id, OrgMembership.org_id == data.org_id,
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if existing is None:
        db.add(
            OrgMembership(
                id=uuid4(), user_id=user.id, org_id=data.org_id,
                role=_role_enum(data.role), created_at=now, updated_at=now,
            )
        )
    else:
        existing.role = _role_enum(data.role)
    await db.flush()
    return await _enrich_user(db, user)


@router.patch(
    "/users/{user_id}/memberships/{org_id}", response_model=UserPublic
)
async def update_membership(
    user_id: UUID, org_id: UUID, data: MembershipRoleUpdate,
    auth: CurrentAuth, db: Db,
) -> UserPublic:
    await _require_org_admin(db, auth, org_id)
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404)
    m = (
        await db.execute(
            select(OrgMembership).where(
                OrgMembership.user_id == user_id, OrgMembership.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="membership not found")
    m.role = _role_enum(data.role)
    await db.flush()
    return await _enrich_user(db, user)


@router.delete(
    "/users/{user_id}/memberships/{org_id}", status_code=204
)
async def remove_membership(
    user_id: UUID, org_id: UUID, auth: CurrentAuth, db: Db
) -> None:
    await _require_org_admin(db, auth, org_id)
    m = (
        await db.execute(
            select(OrgMembership).where(
                OrgMembership.user_id == user_id, OrgMembership.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404)
    await db.delete(m)
    await db.flush()


@router.post("/users/{user_id}/reset-invite", response_model=InviteResult)
async def reset_invite(user_id: UUID, auth: CurrentAuth, db: Db) -> InviteResult:
    """Generate a fresh invite token so the user can set a new password."""
    me = await db.get(User, auth.user_id)
    if me is None:
        raise HTTPException(status_code=401)
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404)
    if not me.is_platform_admin:
        # Org admin: only if shared org
        shared = (
            await db.execute(
                select(OrgMembership).where(
                    OrgMembership.user_id == target.id,
                    OrgMembership.org_id.in_(
                        select(OrgMembership.org_id).where(
                            OrgMembership.user_id == me.id,
                            OrgMembership.role.in_([OrgRole.OWNER, OrgRole.ADMIN]),
                        )
                    ),
                )
            )
        ).first()
        if shared is None:
            raise HTTPException(status_code=403)

    target.invite_token = token_urlsafe(32)
    target.invited_at = datetime.now(UTC)
    target.invited_by = me.id
    await db.flush()
    return InviteResult(
        ok=True, user_id=target.id,
        invite_url=f"/accept-invite?token={target.invite_token}",
        detail=f"Nieuwe uitnodigingslink aangemaakt voor {target.email}.",
    )





# ===== Signed SEPA mandates (sign.it-gemak.nl) =====

from pathlib import Path as _Path
from fastapi.responses import FileResponse as _FileResponse
from salespilot.models.signing import SignedMandate as _SignedMandate


class SignedMandatePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    umr: str
    debtor_name: str
    debtor_email: str
    debtor_iban: str
    debtor_city: str
    debtor_kvk: str | None = None
    sign_place: str
    kvk_verified: bool
    status: str
    ip_address: str | None = None
    geo_country: str | None = None
    geo_city: str | None = None
    pdf_sha256: str | None = None
    has_pdf: bool = False
    emailed_at: datetime | None = None
    email_error: str | None = None
    created_at: datetime


@router.get("/mandates", response_model=list[SignedMandatePublic])
async def list_mandates(
    auth: CurrentAuth, db: Db, limit: int = 200,
) -> list[SignedMandatePublic]:
    """List signed SEPA mandates for this org. Visible to all logged-in
    users (no platform-admin requirement) so the sales team can see what
    customers signed; deletion is admin-only (separate endpoint)."""
    # signed_mandates is NOT tenant-scoped via RLS (public submissions),
    # so we filter by org_id explicitly using the caller's org.
    rows = (
        await db.execute(
            select(_SignedMandate)
            .where(_SignedMandate.org_id == auth.org_id)
            .order_by(_SignedMandate.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    out: list[SignedMandatePublic] = []
    for r in rows:
        has_pdf = bool(r.pdf_path) and _Path(r.pdf_path).exists()
        out.append(SignedMandatePublic(
            id=r.id, umr=r.umr,
            debtor_name=r.debtor_name, debtor_email=r.debtor_email,
            debtor_iban=r.debtor_iban, debtor_city=r.debtor_city,
            debtor_kvk=r.debtor_kvk, sign_place=r.sign_place,
            kvk_verified=r.kvk_verified, status=r.status,
            ip_address=r.ip_address,
            geo_country=r.geo_country, geo_city=r.geo_city,
            pdf_sha256=r.pdf_sha256, has_pdf=has_pdf,
            emailed_at=r.emailed_at, email_error=r.email_error,
            created_at=r.created_at,
        ))
    return out


@router.get("/mandates/{mandate_id}")
async def get_mandate_detail(
    mandate_id: UUID, auth: CurrentAuth, db: Db,
) -> dict[str, Any]:
    """Full mandate detail incl. signature base64 + full audit trail.
    Used by the admin detail drawer; PDF is fetched separately."""
    row = await db.get(_SignedMandate, mandate_id)
    if row is None or row.org_id != auth.org_id:
        raise HTTPException(status_code=404, detail="mandate not found")
    return {
        "id": str(row.id),
        "umr": row.umr,
        "debtor_name": row.debtor_name,
        "debtor_address": row.debtor_address,
        "debtor_postcode": row.debtor_postcode,
        "debtor_city": row.debtor_city,
        "debtor_country": row.debtor_country,
        "debtor_iban": row.debtor_iban,
        "debtor_bic": row.debtor_bic,
        "debtor_email": row.debtor_email,
        "debtor_phone": row.debtor_phone,
        "debtor_kvk": row.debtor_kvk,
        "sign_place": row.sign_place,
        "signature_png_base64": row.signature_png_base64,
        "ip_address": row.ip_address,
        "user_agent": row.user_agent,
        "geo_country": row.geo_country,
        "geo_region": row.geo_region,
        "geo_city": row.geo_city,
        "geo_lat": float(row.geo_lat) if row.geo_lat is not None else None,
        "geo_lon": float(row.geo_lon) if row.geo_lon is not None else None,
        "kvk_verified": row.kvk_verified,
        "kvk_verified_at": row.kvk_verified_at.isoformat() if row.kvk_verified_at else None,
        "kvk_raw": row.kvk_raw,
        "pdf_sha256": row.pdf_sha256,
        "has_pdf": bool(row.pdf_path) and _Path(row.pdf_path).exists(),
        "status": row.status,
        "emailed_at": row.emailed_at.isoformat() if row.emailed_at else None,
        "email_error": row.email_error,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/mandates/{mandate_id}/pdf")
async def get_mandate_pdf(
    mandate_id: UUID, auth: CurrentAuth, db: Db,
) -> _FileResponse:
    """Stream the stored PDF for this mandate."""
    row = await db.get(_SignedMandate, mandate_id)
    if row is None or row.org_id != auth.org_id:
        raise HTTPException(status_code=404, detail="mandate not found")
    if not row.pdf_path:
        raise HTTPException(status_code=404, detail="PDF not generated for this mandate")
    p = _Path(row.pdf_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="PDF file missing on disk")
    return _FileResponse(
        path=str(p),
        media_type="application/pdf",
        filename=f"SEPA-mandaat-{row.umr}.pdf",
    )


@router.post("/mandates/{mandate_id}/resend-email")
async def resend_mandate_email(
    mandate_id: UUID, auth: CurrentAuth, db: Db,
) -> dict[str, Any]:
    """Re-send the mandate PDF to administratie@it-gemak.nl + debtor.
    Used when the original delivery failed (status='failed' / email_error
    populated). The PDF on disk is reused -- we don't re-render."""
    row = await db.get(_SignedMandate, mandate_id)
    if row is None or row.org_id != auth.org_id:
        raise HTTPException(status_code=404, detail="mandate not found")
    if not row.pdf_path or not _Path(row.pdf_path).exists():
        raise HTTPException(status_code=400, detail="PDF missing; cannot resend")

    from salespilot.api.sign import _send_mandate_email
    pdf_bytes = _Path(row.pdf_path).read_bytes()

    # Reconstruct the SubmitRequest-shaped object the helper needs
    class _Stub:
        debtor_name = row.debtor_name
        debtor_address = row.debtor_address
        debtor_postcode = row.debtor_postcode
        debtor_city = row.debtor_city
        debtor_country = row.debtor_country
        debtor_iban = row.debtor_iban
        debtor_bic = row.debtor_bic
        debtor_email = row.debtor_email
        debtor_phone = row.debtor_phone
        debtor_kvk = row.debtor_kvk
        sign_place = row.sign_place
    try:
        await _send_mandate_email(
            umr=row.umr, debtor=_Stub(),
            pdf_bytes=pdf_bytes, kvk_verified=row.kvk_verified,
        )
        row.status = "emailed"
        row.emailed_at = datetime.now(UTC)
        row.email_error = None
        await db.commit()
        return {"ok": True}
    except Exception as e:
        row.email_error = str(e)[:500]
        await db.commit()
        raise HTTPException(status_code=502, detail=str(e)[:200])
