"""Async Openprovider API v1beta client.

Openprovider's API lives at `https://api.openprovider.eu/v1beta/` with
JWT auth. Their auth flow:

    1. POST /auth/login {username, password, ip}  -> {token}
    2. Token lasts ~24h, refresh by re-login

Endpoints we use:
    POST /auth/login                 -- get JWT
    GET  /domains                    -- list domains
    GET  /domains/{id}               -- single domain detail
    GET  /customers                  -- contact handles

Pagination uses ?offset=N&limit=100.

Reality check:
    - Openprovider doesn't yet support API-key headers like Cloudflare
      does -- you authenticate as a user, optionally restricted by IP.
    - Recommendation per their docs: create a dedicated 'API user' in
      Openprovider with read-only role + IP allowlist for our box.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel


class OpenproviderError(Exception):
    pass


class OpenproviderCredentials(BaseModel):
    username: str
    password: str
    base_url: str = "https://api.openprovider.eu"
    # Optional IP that Openprovider should accept the token from.
    # Leave empty to let Openprovider derive it from the request.
    bound_ip: str | None = None


class OpenproviderClient:
    def __init__(
        self, creds: OpenproviderCredentials, timeout_s: float = 30.0,
    ) -> None:
        self.creds = creds
        self.base = creds.base_url.rstrip("/")
        self._token: str | None = None
        self._token_expires_at: datetime | None = None
        self._client = httpx.AsyncClient(timeout=timeout_s)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "OpenproviderClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def _ensure_token(self) -> str:
        now = datetime.now(UTC)
        if (
            self._token
            and self._token_expires_at
            and now < self._token_expires_at - timedelta(hours=1)
        ):
            return self._token
        body: dict[str, Any] = {
            "username": self.creds.username,
            "password": self.creds.password,
        }
        if self.creds.bound_ip:
            body["ip"] = self.creds.bound_ip
        try:
            res = await self._client.post(
                f"{self.base}/v1beta/auth/login",
                json=body,
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as e:
            raise OpenproviderError(f"login failed: {e}") from e
        if res.status_code != 200:
            raise OpenproviderError(
                f"login returned {res.status_code}: {res.text[:200]}"
            )
        data = res.json() or {}
        token = (data.get("data") or {}).get("token") or data.get("token")
        if not token:
            raise OpenproviderError(f"login response missing token: {data!r}")
        self._token = token
        # Openprovider tokens last 24h. Cache for 23h.
        self._token_expires_at = now + timedelta(hours=23)
        return token

    async def _request(
        self, method: str, path: str,
        *, params: dict[str, Any] | None = None, json: Any = None,
    ) -> Any:
        token = await self._ensure_token()
        url = f"{self.base}/v1beta{path}" if path.startswith("/") else f"{self.base}/v1beta/{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        if json is not None:
            headers["Content-Type"] = "application/json"
        try:
            res = await self._client.request(
                method, url, headers=headers, params=params, json=json,
            )
        except httpx.HTTPError as e:
            raise OpenproviderError(f"{method} {path} failed: {e}") from e
        if res.status_code == 401:
            # Token rejected mid-flight; clear so next call re-logins
            self._token = None
            raise OpenproviderError("401: token afgewezen, opnieuw inloggen vereist")
        if res.status_code == 403:
            raise OpenproviderError("403: gebruiker heeft geen rechten op deze resource")
        if res.status_code >= 400:
            raise OpenproviderError(
                f"{method} {path} returned {res.status_code}: {res.text[:300]}"
            )
        return res.json() if res.content else None

    # ------------------------------------------------------------------
    # Domains
    # ------------------------------------------------------------------

    async def list_domains(
        self, limit: int = 100, offset: int = 0,
    ) -> list[dict[str, Any]]:
        d = await self._request(
            "GET", "/domains",
            params={"limit": limit, "offset": offset},
        )
        if isinstance(d, dict):
            data = d.get("data") or {}
            return data.get("results") or data.get("domains") or []
        return []

    async def list_all_domains(self) -> list[dict[str, Any]]:
        """Page through all domains. Stops when fewer than `limit` are
        returned in a batch."""
        out: list[dict[str, Any]] = []
        offset = 0
        page_size = 100
        for _ in range(100):  # hard cap 10k domains
            page = await self.list_domains(limit=page_size, offset=offset)
            if not page:
                break
            out.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        return out

    async def get_domain(self, domain_id: int) -> dict[str, Any] | None:
        d = await self._request("GET", f"/domains/{domain_id}")
        if isinstance(d, dict):
            return d.get("data") or d
        return None

    # ------------------------------------------------------------------
    # Test connection
    # ------------------------------------------------------------------

    async def test_connection(self) -> dict[str, Any]:
        domains = await self.list_domains(limit=1)
        # Probeer ook even count uit list-response te halen
        d_total = await self._request("GET", "/domains", params={"limit": 1})
        total = 0
        if isinstance(d_total, dict):
            total = (d_total.get("data") or {}).get("total") or 0
        return {
            "ok": True,
            "first_domain": domains[0].get("domain") if domains else None,
            "total_domains": total or len(domains),
            "checked_at": datetime.now(UTC).isoformat(),
        }
