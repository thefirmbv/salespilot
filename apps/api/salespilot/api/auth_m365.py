"""Microsoft 365 SSO via Azure AD OAuth2 authorization-code flow.

Flow:
  1. User clicks "Sign in with Microsoft" on /login
  2. Browser GET /api/v1/auth/m365/login
     -> 302 to Microsoft's authorize endpoint with our client_id + redirect_uri
  3. After consent Microsoft redirects to /api/v1/auth/m365/callback?code=...
  4. We exchange the code for an access token, fetch /me to get email + name
  5. Look up the user by email:
        - found:   issue access+refresh JWT, set cookie, redirect to /
        - not-found and allowed_email_domains matches: optionally auto-create
        - otherwise: redirect to /login?error=not_provisioned

Config (kind=m365_sso in integrations table):
  tenant_id              -- Azure tenant GUID or 'common'
  client_id              -- Azure app Application (client) ID
  client_secret          -- Stored encrypted
  allowed_email_domains  -- List of strings, e.g. ["it-gemak.nl"]
  auto_create_users      -- Bool. If true, unknown emails matching an allowed
                            domain get a new User + membership in the default
                            org with role=member.

The SSO config is per-org. In practice for now we use the FIRST org that has
SSO enabled and matches the email domain; this is sufficient for IT-Gemak
where SSO will be used for internal staff.
"""

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from salespilot.db import raw_session
from salespilot.models.auth import Organization, OrgMembership, OrgRole, User
from salespilot.models.integrations import Integration
from salespilot.security import create_access_token, create_refresh_token


router = APIRouter(prefix="/auth/m365", tags=["auth"])


def _redirect_uri(request: Request) -> str:
    # Build the absolute redirect URL. We trust the X-Forwarded-Proto/Host
    # because Caddy sets these (config in compose/caddy/Caddyfile).
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
    return f"{scheme}://{host}/api/v1/auth/m365/callback"


def _login_redirect(error: str | None = None) -> RedirectResponse:
    target = "/login"
    if error:
        target += f"?sso_error={error}"
    return RedirectResponse(target, status_code=status.HTTP_302_FOUND)


async def _find_sso_config() -> tuple[Integration, Organization] | None:
    """Pick the first organization with an enabled M365 SSO integration.

    Integration is TenantScoped via RLS so we can't query across orgs
    with raw_session() -- the policy would filter every row out. We
    iterate over every Organization and probe its tenant_session.
    """
    from salespilot.db import tenant_session
    async with raw_session() as db:
        orgs = (
            await db.execute(select(Organization).order_by(Organization.created_at))
        ).scalars().all()

    for org in orgs:
        async with tenant_session(org.id) as db:
            integ = (
                await db.execute(
                    select(Integration).where(
                        Integration.kind == "m365_sso",
                        Integration.is_enabled == True,  # noqa: E712
                    )
                )
            ).scalar_one_or_none()
            if integ is not None:
                # Detach from this session by re-fetching the org plain
                org_obj = await db.get(Organization, org.id)
                # Eager-load the JSON config so we don't lazy-load on a
                # closed session further on
                _ = integ.config_json
                if org_obj is not None:
                    # Expunge so callers can read attrs after session close
                    db.expunge(integ)
                    db.expunge(org_obj)
                    return integ, org_obj
    return None


@router.get("/login")
async def m365_login(request: Request) -> RedirectResponse:
    """Kick off the OAuth flow."""
    sso = await _find_sso_config()
    if sso is None:
        return _login_redirect(error="sso_not_configured")
    integ, _org = sso
    cfg = integ.config_json or {}
    client_id = cfg.get("client_id")
    tenant = cfg.get("tenant_id") or "common"
    if not client_id:
        return _login_redirect(error="sso_not_configured")

    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": _redirect_uri(request),
        "response_mode": "query",
        "scope": "openid email profile User.Read",
        "prompt": "select_account",
    }
    url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?{urlencode(params)}"
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


@router.get("/callback")
async def m365_callback(request: Request, code: str | None = None, error: str | None = None) -> RedirectResponse:
    if error:
        return _login_redirect(error=error)
    if not code:
        return _login_redirect(error="missing_code")

    sso = await _find_sso_config()
    if sso is None:
        return _login_redirect(error="sso_not_configured")
    integ, default_org = sso
    cfg = integ.config_json or {}
    client_id = cfg.get("client_id")
    client_secret = cfg.get("client_secret")
    tenant = cfg.get("tenant_id") or "common"
    if not client_id or not client_secret:
        return _login_redirect(error="sso_not_configured")

    # Exchange the code for an access token.
    async with httpx.AsyncClient(timeout=15.0) as http:
        token_resp = await http.post(
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": _redirect_uri(request),
                "grant_type": "authorization_code",
            },
        )
        if not token_resp.is_success:
            return _login_redirect(error="token_exchange_failed")
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            return _login_redirect(error="no_access_token")

        # Fetch user profile from Microsoft Graph
        prof_resp = await http.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if not prof_resp.is_success:
            return _login_redirect(error="graph_failed")
        profile = prof_resp.json()

    email = (
        profile.get("mail")
        or profile.get("userPrincipalName")
        or ""
    ).strip().lower()
    if not email:
        return _login_redirect(error="no_email")

    allowed = cfg.get("allowed_email_domains") or []
    if isinstance(allowed, str):
        allowed = [d.strip().lower() for d in allowed.split(",") if d.strip()]
    elif isinstance(allowed, list):
        allowed = [str(d).strip().lower() for d in allowed if d]

    if allowed and not any(email.endswith("@" + d) for d in allowed):
        return _login_redirect(error="domain_not_allowed")

    full_name = profile.get("displayName")

    async with raw_session() as db:
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if user is None:
            # Hard rule: invitation-only. SSO never auto-creates users
            # regardless of the integration config -- this avoids the
            # 'anyone in our tenant can self-provision' foot-gun.
            return _login_redirect(error="user_not_provisioned")

        user.last_login_at = datetime.now(UTC)
        # Pick the user's first membership for the token's org context.
        m = (
            await db.execute(
                select(OrgMembership).where(OrgMembership.user_id == user.id).limit(1)
            )
        ).scalar_one_or_none()
        if m is None:
            return _login_redirect(error="no_membership")
        await db.commit()

        access, _exp = create_access_token(str(user.id), str(m.org_id))
        refresh, _rexp = create_refresh_token(str(user.id))

    # Drop the tokens into a short-lived URL fragment so the frontend can
    # pick them up. Avoids storing tokens server-side in a session.
    # The /login page reads #access_token=...&refresh_token=... on mount.
    fragment = urlencode({"access_token": access, "refresh_token": refresh})
    return RedirectResponse(f"/login#{fragment}", status_code=status.HTTP_302_FOUND)
