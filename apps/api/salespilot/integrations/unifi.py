"""Async UniFi Site Manager API client.

Ubiquiti's cloud API at api.ui.com exposes ALL UniFi consoles (Dream
Machines, UDM-Pro, UCG, etc.) under one account behind a single
X-API-KEY header. No per-site tunneling required.

Auth:
    X-API-KEY: <key from unifi.ui.com profile>

Endpoints we use:
    GET /ea/hosts              -- all consoles under the account
    GET /ea/sites              -- network sites + per-site counters
    GET /ea/devices            -- all managed devices grouped by host
    GET /ea/hosts/{id}         -- detail for one console
    GET /ea/sites/{id}/isp-metrics  -- ISP up/down history

Rate limit: 100 req/min on default tier. We poll all four list-endpoints
per cycle, so 4 req/cycle * 30 cycles/hour ~= 120 req/hour. Well under
the limit even at 60s polling.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel


class UniFiError(Exception):
    pass


class UniFiCredentials(BaseModel):
    api_key: str
    base_url: str = "https://api.ui.com"


class UniFiClient:
    def __init__(self, creds: UniFiCredentials, timeout_s: float = 30.0) -> None:
        self.creds = creds
        self.base = creds.base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout_s)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "UniFiClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def _get(self, path: str, **params: Any) -> Any:
        url = f"{self.base}{path}"
        try:
            res = await self._client.get(
                url,
                headers={
                    "X-API-KEY": self.creds.api_key,
                    "Accept": "application/json",
                },
                params=params or None,
            )
        except httpx.HTTPError as e:
            raise UniFiError(f"GET {path} failed: {e}") from e
        if res.status_code == 401:
            raise UniFiError("401: API key ongeldig of ingetrokken")
        if res.status_code == 403:
            raise UniFiError("403: API key heeft geen toegang tot deze resource")
        if res.status_code == 429:
            raise UniFiError("429: rate-limit overschreden (100 req/min)")
        if res.status_code >= 400:
            raise UniFiError(f"GET {path} returned {res.status_code}: {res.text[:300]}")
        if not res.content:
            return None
        return res.json()

    # ------------------------------------------------------------------
    # Hosts (consoles: UDM, UDM-Pro, UCG, UDR, ...)
    # ------------------------------------------------------------------

    async def list_hosts(self) -> list[dict[str, Any]]:
        """All UniFi consoles under the account. Returns the raw `data`
        array exactly as api.ui.com gives it. Caller is expected to map
        the fields it cares about."""
        d = await self._get("/ea/hosts")
        return d.get("data", []) if isinstance(d, dict) else []

    async def get_host(self, host_id: str) -> dict[str, Any] | None:
        d = await self._get(f"/ea/hosts/{host_id}")
        if isinstance(d, dict):
            return d.get("data") or d
        return None

    # ------------------------------------------------------------------
    # Sites (per-host network/Protect/Access sites)
    # ------------------------------------------------------------------

    async def list_sites(self) -> list[dict[str, Any]]:
        d = await self._get("/ea/sites")
        return d.get("data", []) if isinstance(d, dict) else []

    # ------------------------------------------------------------------
    # Devices (AP's, switches, gateways, cameras, ...)
    # ------------------------------------------------------------------

    async def list_devices(self) -> list[dict[str, Any]]:
        """Returns ALL devices grouped by host:
            [{"hostId": "...", "hostName": "...", "devices": [...]}, ...]
        Each device row has id, mac, name, model, shortname, ip,
        productLine, status, version, firmwareStatus, updateAvailable,
        isConsole, isManaged, startupTime, uidb (icon refs).
        """
        d = await self._get("/ea/devices")
        return d.get("data", []) if isinstance(d, dict) else []

    # ------------------------------------------------------------------
    # ISP metrics (WAN uptime per site)
    # ------------------------------------------------------------------

    async def isp_metrics(
        self, host_id: str, site_id: str,
        metric_type: str = "5m",  # 5m | 1h | 1d
    ) -> dict[str, Any] | None:
        """ISP up/down + speed history. Path differs slightly by API
        revision; we try both common shapes and surface the first hit."""
        for path in (
            f"/ea/sites/{site_id}/isp-metrics",
            f"/ea/hosts/{host_id}/sites/{site_id}/isp-metrics",
        ):
            try:
                d = await self._get(path, type=metric_type)
                if isinstance(d, dict):
                    return d
            except UniFiError:
                continue
        return None

    # ------------------------------------------------------------------
    # Convenience: connection test
    # ------------------------------------------------------------------

    async def test_connection(self) -> dict[str, Any]:
        hosts = await self.list_hosts()
        sites = await self.list_sites()
        devs = await self.list_devices()
        # Count online/offline devices for the test output
        total_devs = sum(len(h.get("devices", [])) for h in devs)
        online = sum(
            1 for h in devs for d in h.get("devices", [])
            if d.get("status") == "online"
        )
        return {
            "ok": True,
            "hosts": len(hosts),
            "sites": len(sites),
            "devices": total_devs,
            "devices_online": online,
            "devices_offline": total_devs - online,
            "checked_at": datetime.now(UTC).isoformat(),
        }
