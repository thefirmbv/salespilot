"""NMBRS REST API client met OAuth 2.0 + subscription-key auth.

Twee headers verplicht op iedere call:
  Authorization: Bearer <access_token>     (van /connect/token)
  X-Subscription-Key: <subscription_key>   (uit developer portal)

OAuth flow:
  1. User redirect naar /connect/authorize met client_id + redirect_uri + scope
  2. NMBRS toont consent-scherm, redirect terug met code
  3. We exchangen code voor access_token + refresh_token
  4. access_token: 1 uur geldig
  5. refresh_token: 30 dagen, eenmalig gebruik (= elke refresh geeft nieuw refresh-token)

We bewaren tokens in integration.config_json:
  - access_token, access_token_expires_at
  - refresh_token, refresh_token_expires_at
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, UTC
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from salespilot.models.integrations import Integration


IDENTITY_BASE = "https://identityservice.nmbrs.com"
API_BASE = "https://api.nmbrsapp.com"

# Default scopes voor onze use case
DEFAULT_SCOPES = [
    "openid",
    "offline_access",         # refresh_token
    "employee.info.read",     # naam + email medewerkers
    "employee.absence.read",  # verlof
    "company.info.read",      # bedrijfsstructuur
    "user.info",              # current user info
]


class NmbrsConfigError(Exception):
    """Integration record is incomplete (missing client_id, secret, etc.)"""


class NmbrsAuthError(Exception):
    """OAuth flow / token refresh failed."""


def _get_cfg(integ: Integration) -> dict:
    cfg = integ.config_json or {}
    for k in ("client_id", "client_secret", "subscription_key", "redirect_uri"):
        if not cfg.get(k):
            raise NmbrsConfigError(f"NMBRS integration missing '{k}'")
    return cfg


def build_authorize_url(integ: Integration, state: str,
                        scopes: list[str] | None = None) -> str:
    """Bouw de URL waar de gebruiker naartoe gestuurd wordt voor consent."""
    cfg = _get_cfg(integ)
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "response_type": "code",
        "scope": " ".join(scopes or DEFAULT_SCOPES),
        "state": state,
    }
    return f"{IDENTITY_BASE}/connect/authorize?" + urlencode(params)


async def exchange_code_for_tokens(
    integ: Integration, code: str,
) -> dict[str, Any]:
    """Wissel authorization code in voor access + refresh token."""
    cfg = _get_cfg(integ)
    basic = base64.b64encode(
        f"{cfg['client_id']}:{cfg['client_secret']}".encode()
    ).decode()
    body = urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": cfg["redirect_uri"],
    })
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.post(
            f"{IDENTITY_BASE}/connect/token",
            content=body,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
    if r.status_code != 200:
        raise NmbrsAuthError(f"Token exchange failed: {r.status_code} {r.text}")
    return r.json()


async def refresh_access_token(integ: Integration) -> dict[str, Any]:
    """Gebruik refresh_token om nieuwe access_token + refresh_token te krijgen."""
    cfg = _get_cfg(integ)
    refresh = cfg.get("refresh_token")
    if not refresh:
        raise NmbrsAuthError("No refresh_token available -- user must re-consent")
    basic = base64.b64encode(
        f"{cfg['client_id']}:{cfg['client_secret']}".encode()
    ).decode()
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.post(
            f"{IDENTITY_BASE}/connect/token",
            content=urlencode({
                "grant_type": "refresh_token",
                "refresh_token": refresh,
            }),
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
    if r.status_code != 200:
        raise NmbrsAuthError(f"Refresh failed: {r.status_code} {r.text}")
    return r.json()


def store_tokens(integ: Integration, token_response: dict) -> None:
    """Update integration.config_json met tokens uit response.

    NMBRS retourneert:
      access_token   (JWT)
      expires_in     (seconden, typisch 3600)
      refresh_token  (single-use, 30 dagen)
      token_type     'Bearer'
      scope          'space separated'
    """
    cfg = dict(integ.config_json or {})
    now = datetime.now(UTC)
    cfg["access_token"] = token_response["access_token"]
    cfg["access_token_expires_at"] = (
        now + timedelta(seconds=int(token_response.get("expires_in", 3600)))
    ).isoformat()
    if "refresh_token" in token_response:
        cfg["refresh_token"] = token_response["refresh_token"]
        # Refresh tokens zijn 30 dagen geldig
        cfg["refresh_token_expires_at"] = (
            now + timedelta(days=30)
        ).isoformat()
    cfg["last_token_refresh_at"] = now.isoformat()
    cfg["granted_scopes"] = token_response.get("scope", "").split()
    cfg["status"] = "connected"
    integ.config_json = cfg


async def get_valid_access_token(integ: Integration, db: AsyncSession) -> str:
    """Returnt geldig access_token. Refresh automatisch als bijna verlopen."""
    cfg = integ.config_json or {}
    access = cfg.get("access_token")
    expires_str = cfg.get("access_token_expires_at")
    if access and expires_str:
        expires = datetime.fromisoformat(expires_str)
        # Refresh 5 min voor expiry
        if expires > datetime.now(UTC) + timedelta(minutes=5):
            return access
    # Need to refresh
    new = await refresh_access_token(integ)
    store_tokens(integ, new)
    await db.flush()
    return new["access_token"]


class NmbrsClient:
    """Thin wrapper around NMBRS REST API with auto-refresh."""

    def __init__(self, integ: Integration, db: AsyncSession):
        self.integ = integ
        self.db = db

    async def _headers(self) -> dict[str, str]:
        cfg = _get_cfg(self.integ)
        token = await get_valid_access_token(self.integ, self.db)
        return {
            "Authorization": f"Bearer {token}",
            "X-Subscription-Key": cfg["subscription_key"],
            "Accept": "application/json",
        }

    async def get(self, path: str, params: dict | None = None) -> Any:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.get(
                f"{API_BASE}{path}",
                headers=await self._headers(),
                params=params,
            )
        if r.status_code == 401:
            raise NmbrsAuthError(f"Unauthorized: {r.text}")
        r.raise_for_status()
        return r.json()

    async def companies(self) -> list[dict]:
        """Bedrijven waar deze user toegang toe heeft."""
        return await self.get("/api/companies")

    async def user_info(self) -> dict:
        """Wie ben ik (van NMBRS' kant gezien)."""
        return await self.get("/api/user/info")

    async def employees(self, company_id: str) -> list[dict]:
        """Medewerkers van een bedrijf."""
        return await self.get(f"/api/companies/{company_id}/employees")

    async def employee_personal_info(self, employee_id: str) -> dict:
        """Persoonlijke info (naam, email) voor één medewerker."""
        return await self.get(f"/api/employees/{employee_id}/personalInfo")

    async def employee_absences(
        self, employee_id: str, year: int | None = None,
    ) -> list[dict]:
        """Verlof voor één medewerker."""
        params = {"year": year} if year else None
        return await self.get(f"/api/employees/{employee_id}/absences", params=params)
