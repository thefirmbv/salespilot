"""Async HaloPSA REST client.

HaloPSA's API uses OAuth2 client-credentials. Token endpoint:
    POST {base_url}/auth/token
        body: grant_type=client_credentials&client_id=...&client_secret=...&scope=...

Resource endpoints live under {base_url}/api/<Resource> and return JSON.
We hit:
    GET  /api/Client          list clients
    GET  /api/Client/{id}     single client
    POST /api/Client          create client
    GET  /api/Quotation       list quotations (filterable by client_id)

This client is per-request (built from the org's Integration row). We don't
share a long-lived client across orgs because every tenant has its own
HaloPSA tenancy and credentials.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel


class HaloPSAError(Exception):
    """Raised when HaloPSA returns a non-2xx or the token request fails."""


class HaloPSACredentials(BaseModel):
    base_url: str
    client_id: str
    client_secret: str
    tenant: str | None = None
    scopes: str = "all"


def _normalize_base(url: str) -> str:
    """Accept 'halo.example.com', 'https://halo.example.com', or trailing /."""
    u = url.strip().rstrip("/")
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u


class HaloPSAClient:
    def __init__(self, creds: HaloPSACredentials, timeout_s: float = 20.0) -> None:
        self.creds = creds
        self.base = _normalize_base(creds.base_url)
        self._token: str | None = None
        self._token_expires_at: datetime | None = None
        self._client = httpx.AsyncClient(timeout=timeout_s)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "HaloPSAClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def _ensure_token(self) -> str:
        if (
            self._token
            and self._token_expires_at
            and self._token_expires_at > datetime.now(UTC) + timedelta(seconds=30)
        ):
            return self._token

        url = f"{self.base}/auth/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self.creds.client_id,
            "client_secret": self.creds.client_secret,
            "scope": self.creds.scopes,
        }
        if self.creds.tenant:
            data["tenant"] = self.creds.tenant

        try:
            res = await self._client.post(
                url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as e:
            raise HaloPSAError(f"token request failed: {e}") from e

        if res.status_code != 200:
            raise HaloPSAError(
                f"token request returned {res.status_code}: {res.text[:300]}"
            )

        body = res.json()
        token = body.get("access_token")
        if not token:
            raise HaloPSAError(f"token response missing access_token: {body}")
        self._token = token
        expires_in = int(body.get("expires_in", 3600))
        self._token_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
        return token

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        token = await self._ensure_token()
        url = f"{self.base}{path}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        headers.setdefault("Accept", "application/json")
        try:
            res = await self._client.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as e:
            raise HaloPSAError(f"{method} {path} failed: {e}") from e
        if res.status_code >= 400:
            raise HaloPSAError(
                f"{method} {path} returned {res.status_code}: {res.text[:500]}"
            )
        if not res.content:
            return None
        return res.json()

    async def test_connection(self) -> bool:
        await self._ensure_token()
        return True

    async def list_clients(
        self, page_size: int = 100, max_pages: int = 50
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page = 1
        while page <= max_pages:
            data = await self._request(
                "GET",
                "/api/Client",
                params={
                    "pageinate": "true",
                    "page_size": page_size,
                    "page_no": page,
                    "includeinactive": "false",
                },
            )
            rows: list[dict[str, Any]]
            if isinstance(data, list):
                rows = data
            elif isinstance(data, dict):
                rows = (
                    data.get("clients")
                    or data.get("Clients")
                    or data.get("records")
                    or []
                )
            else:
                rows = []
            out.extend(rows)
            if len(rows) < page_size:
                break
            page += 1
        return out

    async def get_client(self, client_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/api/Client/{client_id}")

    async def create_client(self, payload: dict[str, Any]) -> dict[str, Any]:
        """HaloPSA's /api/Client POST accepts an ARRAY of client objects.
        Wrap a single payload, then unwrap."""
        data = await self._request("POST", "/api/Client", json=[payload])
        if isinstance(data, list) and data:
            return data[0]
        if isinstance(data, dict):
            return data
        raise HaloPSAError(f"unexpected create_client response: {data!r}")

    async def list_quotations_for_client(
        self, client_id: int
    ) -> list[dict[str, Any]]:
        return await self._list_quotations(client_id=client_id)

    async def list_all_quotations(self) -> list[dict[str, Any]]:
        """Single call returning all quotations (with details) across all clients."""
        return await self._list_quotations(client_id=None)

    # ----- Mail campaigns (Marketing module) -----

    async def list_mail_campaigns(self) -> list[dict[str, Any]]:
        """All mail campaigns. Requires the 'Mail Campaign' API permission
        in HaloPSA. Returns [] on 403 so callers can handle gracefully."""
        try:
            data = await self._request(
                "GET",
                "/api/MailCampaign",
                params={"pageinate": "false", "include_details": "true"},
            )
        except HaloPSAError as e:
            if "403" in str(e):
                return []
            raise
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return (
                data.get("mailcampaigns")
                or data.get("mailCampaigns")
                or data.get("campaigns")
                or data.get("records")
                or []
            )
        return []

    async def get_mail_campaign(self, campaign_id: int) -> dict[str, Any] | None:
        """Detail of one campaign (used for recipient lists / engagement)."""
        try:
            data = await self._request("GET", f"/api/MailCampaign/{campaign_id}")
        except HaloPSAError as e:
            if "403" in str(e) or "404" in str(e):
                return None
            raise
        if isinstance(data, dict):
            return data
        return None

    async def _list_quotations(
        self, client_id: int | None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "pageinate": "false",
            # IMPORTANT: without this, response omits status, expiry_date, total, etc.
            "include_details": "true",
        }
        if client_id is not None:
            params["client_id"] = client_id
        data = await self._request("GET", "/api/Quotation", params=params)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return (
                data.get("quotes")
                or data.get("quotations")
                or data.get("records")
                or []
            )
        return []
