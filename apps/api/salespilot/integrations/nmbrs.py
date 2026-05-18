"""NMBRS REST API client met OAuth 2.0 + multi-debtor support.

NMBRS authoriseert per debtor. Eén gebruiker kan toegang hebben tot
meerdere debtors (= environments) met dezelfde NMBRS-login. Voorbeeld:
  - IT-gemak B.V.       (debtorId cb5f8acf-...)
  - The Firm ISP B.V.   (debtorId X)

Bij elke OAuth-consent geef je consent voor ÉÉN debtor. Wij bewaren
daarom een aparte token-set per debtor in config_json:

  config_json = {
    "client_id": "...", "client_secret": "...",
    "subscription_key": "...", "redirect_uri": "...",
    "debtors": {
      "<debtor_uuid>": {
        "name": "IT-gemak B.V.",
        "access_token": "...",
        "access_token_expires_at": "...",
        "refresh_token": "...",
        "refresh_token_expires_at": "...",
        "granted_scopes": [...],
        "last_token_refresh_at": "...",
      },
      "<other_debtor_uuid>": { ... }
    }
  }

Backward compat: bij gebruik van oude top-level tokens worden ze
gemigreerd naar `debtors` dict bij eerste call.

Voor de API:
  Authorization: Bearer <access_token>
  X-Subscription-Key: <subscription_key>
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

DEFAULT_SCOPES = [
    "offline_access",
    "employee.info.read",
    "employee.employment.read",
    "company.info.read",
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


# ---- Debtor-token persistence -------------------------------------


def _migrate_legacy_tokens(integ: Integration) -> None:
    """Verplaats top-level tokens naar debtors[<unknown>] bij oude config.

    Voor de eerste keer dat we multi-debtor draaien: oude single-token
    layout heeft access_token/refresh_token op root. We bewaren ze
    onder een speciale __legacy__ key zodat ze niet onbruikbaar zijn
    maar evenmin botsen met echte debtor-ids.
    """
    cfg = integ.config_json or {}
    if cfg.get("access_token") and "debtors" not in cfg:
        new_cfg = dict(cfg)
        new_cfg["debtors"] = {
            "__legacy__": {
                "name": "Onbekende debtor (legacy token)",
                "access_token": cfg.get("access_token"),
                "access_token_expires_at": cfg.get("access_token_expires_at"),
                "refresh_token": cfg.get("refresh_token"),
                "refresh_token_expires_at": cfg.get("refresh_token_expires_at"),
                "granted_scopes": cfg.get("granted_scopes", []),
                "last_token_refresh_at": cfg.get("last_token_refresh_at"),
            }
        }
        # Verwijder oude top-level token-velden om verwarring te voorkomen
        for k in (
            "access_token", "access_token_expires_at",
            "refresh_token", "refresh_token_expires_at",
            "granted_scopes", "last_token_refresh_at",
        ):
            new_cfg.pop(k, None)
        integ.config_json = new_cfg


def get_debtors(integ: Integration) -> dict[str, dict]:
    """Returnt dict[debtor_id -> token-info]. Migreert legacy."""
    _migrate_legacy_tokens(integ)
    return (integ.config_json or {}).get("debtors", {})


def store_debtor_tokens(
    integ: Integration,
    debtor_id: str,
    debtor_name: str,
    token_response: dict,
) -> None:
    """Sla tokens voor één debtor op. Overschrijft bestaande tokens
    voor dezelfde debtor maar laat andere debtors met rust."""
    cfg = dict(integ.config_json or {})
    debtors = dict(cfg.get("debtors") or {})
    now = datetime.now(UTC)

    debtors[debtor_id] = {
        "name": debtor_name,
        "access_token": token_response["access_token"],
        "access_token_expires_at": (
            now + timedelta(seconds=int(token_response.get("expires_in", 3600)))
        ).isoformat(),
        "refresh_token": token_response.get("refresh_token"),
        "refresh_token_expires_at": (
            now + timedelta(days=30)
        ).isoformat() if token_response.get("refresh_token") else None,
        "granted_scopes": token_response.get("scope", "").split(),
        "last_token_refresh_at": now.isoformat(),
    }
    cfg["debtors"] = debtors
    cfg["status"] = "connected"
    integ.config_json = cfg


# ---- OAuth flow ----------------------------------------------------


def build_authorize_url(integ: Integration, state: str,
                        scopes: list[str] | None = None) -> str:
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


async def refresh_access_token(
    integ: Integration, debtor_id: str,
) -> dict[str, Any]:
    cfg = _get_cfg(integ)
    debtors = get_debtors(integ)
    debtor = debtors.get(debtor_id)
    if not debtor or not debtor.get("refresh_token"):
        raise NmbrsAuthError(
            f"No refresh_token for debtor {debtor_id} -- user must re-consent"
        )
    basic = base64.b64encode(
        f"{cfg['client_id']}:{cfg['client_secret']}".encode()
    ).decode()
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.post(
            f"{IDENTITY_BASE}/connect/token",
            content=urlencode({
                "grant_type": "refresh_token",
                "refresh_token": debtor["refresh_token"],
            }),
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
    if r.status_code != 200:
        raise NmbrsAuthError(f"Refresh failed: {r.status_code} {r.text}")
    return r.json()


async def get_valid_access_token(
    integ: Integration, debtor_id: str, db: AsyncSession,
) -> str:
    """Returns geldig access_token voor één debtor. Refresh automatisch."""
    debtors = get_debtors(integ)
    debtor = debtors.get(debtor_id)
    if not debtor:
        raise NmbrsAuthError(f"Unknown debtor {debtor_id}")
    access = debtor.get("access_token")
    expires_str = debtor.get("access_token_expires_at")
    if access and expires_str:
        try:
            expires = datetime.fromisoformat(expires_str)
            if expires > datetime.now(UTC) + timedelta(minutes=5):
                return access
        except (ValueError, TypeError):
            pass
    # Refresh
    new = await refresh_access_token(integ, debtor_id)
    store_debtor_tokens(integ, debtor_id, debtor.get("name", "Unknown"), new)
    await db.flush()
    return new["access_token"]


# ---- API client ----------------------------------------------------


class NmbrsClient:
    """Thin wrapper around NMBRS REST API voor één debtor."""

    def __init__(self, integ: Integration, debtor_id: str, db: AsyncSession):
        self.integ = integ
        self.debtor_id = debtor_id
        self.db = db

    async def _headers(self) -> dict[str, str]:
        cfg = _get_cfg(self.integ)
        token = await get_valid_access_token(self.integ, self.debtor_id, self.db)
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
            raise NmbrsAuthError(f"401 Unauthorized op {path}: {r.text[:200]}")
        if r.status_code == 403:
            raise NmbrsAuthError(f"403 Forbidden op {path} -- scope mist of debtor heeft geen toegang")
        r.raise_for_status()
        return r.json()

    async def _paginated(self, path: str, params: dict | None = None) -> list[dict]:
        results: list[dict] = []
        page = 1
        while True:
            p = dict(params or {})
            p["pageNumber"] = page
            p.setdefault("pageSize", 100)
            r = await self.get(path, params=p)
            if not isinstance(r, dict):
                if isinstance(r, list):
                    return r
                return []
            results.extend(r.get("data") or [])
            pag = r.get("pagination") or {}
            total_pages = pag.get("totalPages") or 1
            if page >= total_pages:
                break
            page += 1
        return results

    async def debtors(self) -> list[dict]:
        """Debtors waar deze access_token bij hoort.
        Verwacht 1 item terug -- NMBRS tokens zijn altijd debtor-scoped."""
        return await self._paginated("/api/debtors")

    async def companies(self) -> list[dict]:
        return await self._paginated("/api/companies")

    async def employees(self, company_id: str) -> list[dict]:
        return await self._paginated(f"/api/companies/{company_id}/employees")

    async def employee_detail(self, employee_id: str) -> dict | None:
        try:
            r = await self.get(f"/api/employees/{employee_id}")
        except Exception:
            return None
        if isinstance(r, dict):
            data = r.get("data") or []
            if data:
                return data[0]
        return None

    async def employee_absences(
        self, employee_id: str, year: int | None = None,
    ) -> list[dict]:
        try:
            params = {"year": year} if year else None
            return await self._paginated(
                f"/api/employees/{employee_id}/absences", params=params,
            )
        except Exception:
            return []


# ---- Helper: detecteer debtor van vers verkregen token -------------


async def fetch_debtor_for_token(
    access_token: str, subscription_key: str,
) -> tuple[str, str] | None:
    """Met een vers verkregen access_token: haal /api/debtors op
    en return (debtor_id, debtor_name) van de eerste (en enige) debtor.

    NMBRS REST tokens zijn altijd debtor-scoped, dus debtors-lijst is 1 item.
    """
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(
            f"{API_BASE}/api/debtors",
            headers={
                "Authorization": f"Bearer {access_token}",
                "X-Subscription-Key": subscription_key,
                "Accept": "application/json",
            },
            params={"pageNumber": 1, "pageSize": 5},
        )
    if r.status_code != 200:
        return None
    body = r.json()
    if not isinstance(body, dict):
        return None
    data = body.get("data") or []
    if not data:
        return None
    debtor = data[0]
    return (str(debtor["debtorId"]), debtor.get("name") or "Unknown")
