"""Wespennest data-source clients.

Thin async wrappers around the free public APIs used by the Wespennest
pipeline. Each client has a `test_connection()` method so the Settings UI
can verify connectivity without firing real pipeline jobs.

Sources implemented:
  * OpenKVK (overheid.io)   — free Dutch chamber-of-commerce lookups
  * PDOK Locatieserver      — free Dutch geocoder
  * crt.sh                  — free Certificate Transparency search
  * KVK official API        — paid but official; requires API key + ~5d activation

Hunter.io and Apollo.io are commercial/optional and don't get a free
test-call here (would burn the user's quota); their config screen just
stores the key for later pipeline use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class SourceTestResult:
    ok: bool
    detail: str
    sample: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# OpenKVK / overheid.io
# ---------------------------------------------------------------------------


class OpenKvkClient:
    """OpenKVK via overheid.io. Most endpoints work without API key but
    are rate-limited to a few requests per minute. With a free API key
    (https://overheid.io) the limit goes up.

    Search by trade name:   /openkvk?queryFields[handelsnaam]=ACME
    Get by KVK number:      /openkvk/{kvk_number}
    """

    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self.base_url = (base_url or "https://api.overheid.io/openkvk").rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/json"}
        if self.api_key:
            h["ovio-api-key"] = self.api_key
        return h

    async def test_connection(self) -> SourceTestResult:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(
                f"{self.base_url}",
                params={"size": "1"},
                headers=self._headers(),
            )
            if r.status_code == 401:
                return SourceTestResult(
                    ok=False,
                    detail="API-key ongeldig of vereist voor deze hoeveelheid verkeer.",
                )
            if r.status_code == 429:
                return SourceTestResult(
                    ok=False,
                    detail="Rate-limit bereikt. Voeg een gratis API-key toe op overheid.io voor meer requests.",
                )
            if r.is_success:
                data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                count = (
                    (data.get("_embedded") or {}).get("rechtspersoon", [])
                    if isinstance(data, dict)
                    else []
                )
                sample = count[0] if count else None
                return SourceTestResult(
                    ok=True,
                    detail=f"OpenKVK bereikbaar ({r.status_code}). Sample retourneerde {len(count)} item.",
                    sample=sample if isinstance(sample, dict) else None,
                )
            return SourceTestResult(
                ok=False, detail=f"OpenKVK gaf onverwachte status {r.status_code}: {r.text[:120]}",
            )


# ---------------------------------------------------------------------------
# PDOK Locatieserver
# ---------------------------------------------------------------------------


class PdokClient:
    """PDOK Locatieserver — free Dutch geocoder.

    Free.  Stable.  No auth.  Returns {centroide_ll: "POINT(lon lat)"} per
    address.
    """

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or "https://api.pdok.nl").rstrip("/")

    async def test_connection(self) -> SourceTestResult:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(
                f"{self.base_url}/bzk/locatieserver/search/v3_1/free",
                params={"q": "Breukelen", "rows": "1"},
                headers={"Accept": "application/json"},
            )
            if r.is_success:
                data = r.json()
                docs = (data.get("response") or {}).get("docs") or []
                sample = docs[0] if docs else None
                return SourceTestResult(
                    ok=True,
                    detail=f"PDOK Locatieserver bereikbaar ({r.status_code}).",
                    sample=sample if isinstance(sample, dict) else None,
                )
            return SourceTestResult(
                ok=False, detail=f"PDOK gaf status {r.status_code}: {r.text[:120]}"
            )


# ---------------------------------------------------------------------------
# crt.sh
# ---------------------------------------------------------------------------


class CrtShClient:
    """crt.sh — Certificate Transparency log search.

    Free. Slow. Use sparingly. Returns JSON when ?output=json is appended.
    """

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or "https://crt.sh").rstrip("/")

    async def test_connection(self) -> SourceTestResult:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(
                f"{self.base_url}/",
                params={"q": "%.nl", "output": "json"},
                headers={"Accept": "application/json"},
            )
            if r.is_success:
                # crt.sh sometimes returns empty body on heavy load -- treat
                # any 2xx as success since we don't want to claim it's down
                # over a single slow response.
                try:
                    data = r.json()
                    count = len(data) if isinstance(data, list) else 0
                except Exception:
                    count = 0
                return SourceTestResult(
                    ok=True,
                    detail=f"crt.sh bereikbaar ({r.status_code}). Sample retourneerde {count} certificaat-entries.",
                )
            return SourceTestResult(
                ok=False, detail=f"crt.sh gaf status {r.status_code}: {r.text[:120]}"
            )


# ---------------------------------------------------------------------------
# KVK official API
# ---------------------------------------------------------------------------


class KvkClient:
    """Official KVK API (https://developers.kvk.nl).

    Two product keys: basisprofiel (company search) and functionarissen
    (board members). Each requires a separate test call.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        functionarissen_key: str | None = None,
    ) -> None:
        self.base_url = (base_url or "https://api.kvk.nl/api").rstrip("/")
        self.api_key = api_key
        self.functionarissen_key = functionarissen_key

    async def test_connection(self) -> SourceTestResult:
        if not self.api_key:
            return SourceTestResult(
                ok=False, detail="KVK basisprofiel API-key ontbreekt."
            )
        async with httpx.AsyncClient(timeout=15.0) as c:
            # Search for a known KVK record (one of the largest NL companies)
            # so we can verify the key without needing prior input.
            r = await c.get(
                f"{self.base_url}/v2/zoeken",
                params={"kvkNummer": "27312152"},  # Belastingdienst
                headers={
                    "apikey": self.api_key,
                    "Accept": "application/json",
                },
            )
            if r.status_code == 401 or r.status_code == 403:
                return SourceTestResult(
                    ok=False,
                    detail=(
                        f"KVK weigerde de key (HTTP {r.status_code}). Controleer "
                        "of het abonnement actief is en de juiste 'basisprofiel' key gebruikt wordt."
                    ),
                )
            if r.is_success:
                data = r.json()
                count = len((data or {}).get("resultaten") or [])
                detail = f"KVK basisprofiel bereikbaar ({r.status_code}). Sample retourneerde {count} resultaten."
                # Bonus: also test the functionarissen-key if provided
                if self.functionarissen_key:
                    fr = await c.get(
                        f"{self.base_url}/v1/basisprofielen/27312152/functionarissen",
                        headers={
                            "apikey": self.functionarissen_key,
                            "Accept": "application/json",
                        },
                    )
                    if fr.is_success:
                        detail += " Functionarissen-key OK."
                    else:
                        detail += f" Functionarissen-key faalde (HTTP {fr.status_code})."
                return SourceTestResult(ok=True, detail=detail)
            return SourceTestResult(
                ok=False, detail=f"KVK gaf onverwachte status {r.status_code}: {r.text[:120]}"
            )
