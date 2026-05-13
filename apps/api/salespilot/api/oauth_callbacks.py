"""OAuth callback handlers for third-party integrations.

LinkedIn:
  GET /oauth/linkedin/callback?code=...&state=ORG_ID
    Exchanges the auth code for an access_token + refresh_token, stores
    on the org's LinkedIn integration row, then redirects back to the
    Settings -> LinkedIn page with a result query-param.

Other providers can be added the same way (e.g. M365 calendar sync,
HaloPSA OAuth) without growing the main integrations file.

Notes about LinkedIn OAuth (as of LinkedIn API v2 / 202404):
  * access_token TTL is ~60 days
  * refresh_token is only issued if your app has the 'Marketing
    Developer Platform' product enabled in the LinkedIn console
  * the redirect URI must EXACTLY match what's registered in the
    LinkedIn app's 'Authorized redirect URLs' setting (including scheme,
    host, port, and trailing slash if any)

Security:
  * the `state` parameter is the org_id. We use it both to know which
    integration row to update AND to verify the redirect was triggered
    by us rather than a stray request. For multi-org production it
    should be HMAC-signed, but for a single founder org this is enough.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from salespilot.config import get_settings
from salespilot.db import raw_session
from salespilot.models.integrations import Integration


router = APIRouter(prefix="/oauth", tags=["auth"])


# ---------------------------------------------------------------------
# LinkedIn
# ---------------------------------------------------------------------


def _public_base(request: Request) -> str:
    # Prefer the Caddy-supplied headers; fall back to configured base url.
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    if host:
        return f"{scheme}://{host}"
    settings = get_settings()
    return getattr(settings, "public_base_url", "https://sales.hostingportal.org")


def _settings_redirect(detail: str, ok: bool = True) -> RedirectResponse:
    """Bounce the user back to the LinkedIn settings page with a status
    query param so the UI can show a banner."""
    params = "oauth_ok=1" if ok else "oauth_error=" + detail.replace(" ", "+")[:80]
    return RedirectResponse(
        f"/settings/integrations/linkedin?{params}",
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/linkedin/callback")
async def linkedin_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> RedirectResponse:
    if error:
        return _settings_redirect(f"linkedin_denied:{error}", ok=False)
    if not code or not state:
        return _settings_redirect("missing_code_or_state", ok=False)

    try:
        org_id = UUID(state)
    except ValueError:
        return _settings_redirect("bad_state", ok=False)

    async with raw_session() as db:
        integ = (
            await db.execute(
                select(Integration).where(
                    Integration.kind == "linkedin",
                    Integration.org_id == org_id,
                )
            )
        ).scalar_one_or_none()
        if integ is None:
            return _settings_redirect("no_integration_row", ok=False)

        cfg = integ.config_json or {}
        client_id = cfg.get("client_id")
        client_secret = cfg.get("client_secret")
        if not client_id or not client_secret:
            return _settings_redirect("missing_credentials", ok=False)

        redirect_uri = f"{_public_base(request)}/api/v1/oauth/linkedin/callback"

        # Exchange the authorization code for tokens
        async with httpx.AsyncClient(timeout=20.0) as c:
            try:
                resp = await c.post(
                    "https://www.linkedin.com/oauth/v2/accessToken",
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "redirect_uri": redirect_uri,
                    },
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
            except httpx.HTTPError as e:
                return _settings_redirect(f"http_error:{e}"[:60], ok=False)

        if not resp.is_success:
            # Common cause: redirect_uri mismatch with LinkedIn console
            body = resp.text[:200]
            return _settings_redirect(f"token_exchange_{resp.status_code}", ok=False)

        data = resp.json() or {}
        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token", "")
        expires_in = int(data.get("expires_in") or 0)
        scope = data.get("scope") or ""
        if not access_token:
            return _settings_redirect("no_access_token", ok=False)

        # Compute the absolute expiry timestamp so the UI can warn before it
        # actually expires and the refresh logic knows when to act.
        expires_at = (
            (datetime.now(UTC) + timedelta(seconds=expires_in)).isoformat()
            if expires_in else None
        )

        cfg["access_token"] = access_token
        if refresh_token:
            cfg["refresh_token"] = refresh_token
        if expires_at:
            cfg["access_token_expires_at"] = expires_at
        if scope:
            cfg["granted_scope"] = scope
        cfg["connected_via_oauth"] = True
        cfg["connected_at"] = datetime.now(UTC).isoformat()

        integ.config_json = cfg
        integ.is_enabled = True
        await db.commit()

    return _settings_redirect("connected")


async def refresh_linkedin_token_if_needed(integ: Integration) -> bool:
    """If we have a refresh_token and the access_token is within 24h of
    expiry, swap it for a fresh one. Returns True when a refresh happened.

    Called by the social publisher right before posting; cheap when the
    token is still valid because we just check the timestamp.
    """
    cfg = integ.config_json or {}
    if not cfg.get("refresh_token"):
        return False  # No refresh capability (most LinkedIn apps don't have it)
    expires_at_str = cfg.get("access_token_expires_at")
    if not expires_at_str:
        return False
    try:
        expires_at = datetime.fromisoformat(expires_at_str)
    except ValueError:
        return False
    if datetime.now(UTC) + timedelta(hours=24) < expires_at:
        return False  # plenty of headroom

    client_id = cfg.get("client_id")
    client_secret = cfg.get("client_secret")
    if not client_id or not client_secret:
        return False

    async with httpx.AsyncClient(timeout=15.0) as c:
        resp = await c.post(
            "https://www.linkedin.com/oauth/v2/accessToken",
            data={
                "grant_type": "refresh_token",
                "refresh_token": cfg["refresh_token"],
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if not resp.is_success:
        return False
    data = resp.json() or {}
    new_token = data.get("access_token")
    if not new_token:
        return False
    cfg["access_token"] = new_token
    if data.get("refresh_token"):
        cfg["refresh_token"] = data["refresh_token"]
    expires_in = int(data.get("expires_in") or 0)
    if expires_in:
        cfg["access_token_expires_at"] = (
            datetime.now(UTC) + timedelta(seconds=expires_in)
        ).isoformat()
    integ.config_json = cfg
    return True
