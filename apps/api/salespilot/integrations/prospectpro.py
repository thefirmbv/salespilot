"""Async ProspectPRO REST client.

ProspectPRO API docs: https://docs.prospectpro.nl/

The platform exposes both:
  - Prospects: companies you targeted (cold) or that visited your site (warm)
  - Pageviews: per-prospect visit history (we only need this for prospects
    that have visited the site)

Auth is API-key based via the X-Token-Auth header (per ProspectPRO docs).
Base path is `https://api.prospectpro.nl/v1/`.
"""

from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel


class ProspectPROError(Exception):
    pass


class ProspectPROCredentials(BaseModel):
    base_url: str = "api.prospectpro.nl"
    api_key: str


def _normalize_base(url: str) -> str:
    u = url.strip().rstrip("/")
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u


class ProspectPROClient:
    def __init__(self, creds: ProspectPROCredentials, timeout_s: float = 20.0) -> None:
        self.creds = creds
        self.base = _normalize_base(creds.base_url)
        if not self.base.endswith("/v1"):
            self.base = self.base.rstrip("/") + "/v1"
        self._client = httpx.AsyncClient(
            timeout=timeout_s,
            headers={
                # ProspectPRO uses X-Token-Auth per their developer docs.
                # We send the same value as Authorization Bearer too for
                # robustness against alternate auth schemes.
                "X-Token-Auth": creds.api_key,
                "Authorization": f"Bearer {creds.api_key}",
                "Accept": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "ProspectPROClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def _get(self, path: str, **params: Any) -> Any:
        url = f"{self.base}{path}"
        try:
            res = await self._client.get(url, params=params)
        except httpx.HTTPError as e:
            raise ProspectPROError(f"GET {path} failed: {e}") from e
        if res.status_code == 401 or res.status_code == 403:
            raise ProspectPROError(
                f"GET {path} returned {res.status_code}: invalid API key?"
            )
        if res.status_code >= 400:
            raise ProspectPROError(
                f"GET {path} returned {res.status_code}: {res.text[:300]}"
            )
        if not res.content:
            return None
        return res.json()

    async def test_connection(self) -> bool:
        # We hit /prospects with limit=1 — cheapest way to validate auth.
        await self._get("/prospects", limit=1)
        return True

    async def list_prospects(
        self, page_size: int = 100, max_pages: int = 50
    ) -> list[dict[str, Any]]:
        """Fetch all prospects.

        Response shape is one of:
          - {"data": [...], "total": N, "page": P}
          - [...] (raw array)
        We support both.
        """
        out: list[dict[str, Any]] = []
        page = 1
        while page <= max_pages:
            data = await self._get(
                "/prospects",
                limit=page_size,
                page=page,
            )
            rows: list[dict[str, Any]]
            if isinstance(data, list):
                rows = data
            elif isinstance(data, dict):
                rows = (
                    data.get("data")
                    or data.get("prospects")
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

    async def list_pageviews_for_prospect(
        self, prospect_id: str, since: datetime | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if since is not None:
            params["since"] = since.isoformat()
        data = await self._get(f"/prospects/{prospect_id}/pageviews", **params)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("data") or data.get("pageviews") or []
        return []
