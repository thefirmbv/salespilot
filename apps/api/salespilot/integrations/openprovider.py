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


    # ------------------------------------------------------------------
    # Domain availability + price
    # ------------------------------------------------------------------

    async def check_availability(
        self, name: str, extension: str,
    ) -> dict[str, Any]:
        """Check if a domain is available for registration.

        Returns Openprovider's response which contains:
          status: 'free' | 'active' | 'invalid' | 'reserved' | ...
          premium: boolean
          price: { product: { price: x, currency: 'EUR' }, ... } (if premium)
        """
        d = await self._request(
            "POST", "/domains/check",
            json={
                "domains": [{"name": name, "extension": extension}],
                "with_price": True,
            },
        )
        if isinstance(d, dict):
            data = d.get("data") or {}
            results = data.get("results") or []
            if results:
                return results[0]
        return {"status": "unknown"}

    async def get_domain_price(self, extension: str) -> dict[str, Any]:
        """Retail price for one registration year of this TLD.

        Note: this returns YOUR Openprovider price (= reseller price).
        Premium domains have different prices via check_availability.
        """
        try:
            d = await self._request(
                "GET", "/domains/prices",
                params={"extension": extension, "operation": "create", "period": 1},
            )
            if isinstance(d, dict):
                return d.get("data") or {}
        except OpenproviderError:
            pass
        return {}

    # ------------------------------------------------------------------
    # Customer/contact handles
    # ------------------------------------------------------------------

    async def list_customers(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        d = await self._request(
            "GET", "/customers", params={"limit": limit, "offset": offset},
        )
        if isinstance(d, dict):
            data = d.get("data") or {}
            return data.get("results") or []
        return []

    async def create_customer(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a new contact handle. Openprovider requires:
          - company_name (or first_name + last_name for personal)
          - email
          - phone in E.164 format (+31...)
          - address (city, country, street, zipcode)
          - locale (e.g. 'nl_NL')
        """
        d = await self._request("POST", "/customers", json=payload)
        if isinstance(d, dict):
            return d.get("data") or {}
        return {}

    # ------------------------------------------------------------------
    # Domain registration (THE money endpoint)
    # ------------------------------------------------------------------

    async def register_domain(
        self,
        name: str, extension: str,
        period: int = 1,
        owner_handle: str | None = None,
        admin_handle: str | None = None,
        tech_handle: str | None = None,
        billing_handle: str | None = None,
        name_servers: list[str] | None = None,
        auto_renew: bool = True,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Register a new domain. Returns Openprovider's response
        containing the new domain id on success. Caller is expected
        to have already done check_availability + price preview.

        WARNING: this is a real registration that costs money.
        """
        payload: dict[str, Any] = {
            "domain": {"name": name, "extension": extension},
            "period": period,
            "autorenew": "on" if auto_renew else "off",
        }
        if owner_handle:
            payload["owner_handle"] = owner_handle
        if admin_handle:
            payload["admin_handle"] = admin_handle
        if tech_handle:
            payload["tech_handle"] = tech_handle
        if billing_handle:
            payload["billing_handle"] = billing_handle
        if name_servers:
            payload["name_servers"] = [{"name": ns} for ns in name_servers]
        if extra:
            payload.update(extra)
        d = await self._request("POST", "/domains", json=payload)
        if isinstance(d, dict):
            return d.get("data") or {}
        return {}

    # ------------------------------------------------------------------
    # Domain modification + cancellation
    # ------------------------------------------------------------------

    async def update_autorenew(
        self, domain_id: int, auto_renew: bool,
    ) -> dict[str, Any]:
        """Toggle auto-renew. The soft 'cancel' = set to off; domain
        will expire on its current expiry_date. Reversible."""
        d = await self._request(
            "PUT", f"/domains/{domain_id}",
            json={"autorenew": "on" if auto_renew else "off"},
        )
        return (d or {}).get("data") if isinstance(d, dict) else {}

    async def cancel_domain(self, domain_id: int) -> dict[str, Any]:
        """Hard cancel. Only valid within Openprovider's grace period
        (~5 days after registration for most TLDs). NOT REVERSIBLE."""
        d = await self._request("DELETE", f"/domains/{domain_id}")
        return (d or {}).get("data") if isinstance(d, dict) else {}
