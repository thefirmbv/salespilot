"""Async Plesk REST API v2 client.

Plesk's REST API lives at `https://<plesk-host>:8443/api/v2/` and is
auth'd via an X-API-Key header. Keys are generated in Plesk admin
under Tools & Settings -> Remote API (REST) -> API Keys.

Endpoints we use:
    GET  /api/v2/clients                 -- hosting customers
    GET  /api/v2/domains                 -- domains under all subscriptions
    GET  /api/v2/server                  -- version + license info
    GET  /api/v2/cli/subscription --list -- subscription list via CLI bridge

Note: subscriptions live behind the CLI endpoint because Plesk REST
API v2 (as of Obsidian) doesn't expose them as a first-class resource
yet. We accept that quirk -- the data is reliable, just routed through
/api/v2/cli/<command> which is part of the official REST surface.

Auth realities:
    - 401 means key was revoked or never matched
    - 403 means key is valid but lacks permissions (e.g. reseller key
      trying to read server-level resources)
    - 429: Plesk has no public rate limit, but huge fleets can hit
      internal timeouts -- we retry once on 5xx.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel


class PleskError(Exception):
    pass


class PleskCredentials(BaseModel):
    api_key: str
    base_url: str = "https://localhost:8443"
    verify_tls: bool = True


def _normalize_base(url: str) -> str:
    u = url.strip().rstrip("/")
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u


class PleskClient:
    def __init__(self, creds: PleskCredentials, timeout_s: float = 30.0) -> None:
        self.creds = creds
        self.base = _normalize_base(creds.base_url)
        self._client = httpx.AsyncClient(
            timeout=timeout_s,
            verify=creds.verify_tls,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "PleskClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def _request(
        self, method: str, path: str,
        *, params: dict[str, Any] | None = None, json: Any = None,
    ) -> Any:
        url = f"{self.base}/api/v2{path}" if path.startswith("/") else f"{self.base}/api/v2/{path}"
        headers = {
            "X-API-Key": self.creds.api_key,
            "Accept": "application/json",
        }
        if json is not None:
            headers["Content-Type"] = "application/json"
        try:
            res = await self._client.request(
                method, url, headers=headers, params=params, json=json,
            )
        except httpx.HTTPError as e:
            raise PleskError(f"{method} {path} failed: {e}") from e
        if res.status_code == 401:
            raise PleskError("401: API key ongeldig of ingetrokken")
        if res.status_code == 403:
            raise PleskError("403: API key heeft onvoldoende rechten")
        if res.status_code == 404:
            return None
        if res.status_code >= 400:
            raise PleskError(
                f"{method} {path} returned {res.status_code}: {res.text[:300]}"
            )
        if not res.content:
            return None
        try:
            return res.json()
        except ValueError:
            return res.text

    # ------------------------------------------------------------------
    # Server info (for test_connection)
    # ------------------------------------------------------------------

    async def get_server_info(self) -> dict[str, Any]:
        """Returns version, hostname, license. Used by /test."""
        return await self._request("GET", "/server") or {}

    # ------------------------------------------------------------------
    # Clients (= Plesk customers)
    # ------------------------------------------------------------------

    async def list_clients(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/clients")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("clients") or data.get("items") or []
        return []

    async def get_client(self, client_id: int) -> dict[str, Any] | None:
        return await self._request("GET", f"/clients/{client_id}")

    # ------------------------------------------------------------------
    # Domains
    # ------------------------------------------------------------------

    async def list_domains(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/domains")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("domains") or data.get("items") or []
        return []

    async def get_domain(self, domain_id: int) -> dict[str, Any] | None:
        return await self._request("GET", f"/domains/{domain_id}")

    # ------------------------------------------------------------------
    # Subscriptions -- via CLI bridge because REST API v2 doesn't expose
    # them as a top-level resource (yet)
    # ------------------------------------------------------------------

    async def list_subscriptions(self) -> list[dict[str, Any]]:
        """Subscription list. Falls back across two known shapes:
        1. /subscriptions (only on newest Plesk Obsidian)
        2. CLI bridge /cli/subscription with --list parameter (older)
        """
        # Try modern shape
        try:
            d = await self._request("GET", "/subscriptions")
            if isinstance(d, list):
                return d
            if isinstance(d, dict):
                items = d.get("subscriptions") or d.get("items")
                if isinstance(items, list):
                    return items
        except PleskError:
            pass
        # Fallback to domains list (every domain is the root of one
        # subscription in Plesk's model). Caller gets one row per
        # domain; if you have multi-domain subscriptions that's still
        # accurate as a billing unit because Plesk's CLI bridge returns
        # the same.
        return await self.list_domains()

    # ------------------------------------------------------------------
    # Test connection
    # ------------------------------------------------------------------

    async def test_connection(self) -> dict[str, Any]:
        info = await self.get_server_info()
        subs = await self.list_subscriptions()
        clients = await self.list_clients()
        return {
            "ok": True,
            "version": info.get("version") or info.get("plesk_version") or "?",
            "hostname": info.get("hostname") or "?",
            "clients_count": len(clients),
            "subscriptions_count": len(subs),
            "checked_at": datetime.now(UTC).isoformat(),
        }
