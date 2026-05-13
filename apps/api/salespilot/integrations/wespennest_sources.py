"""Wespennest data-source clients.

Thin async wrappers around the public APIs used by the Wespennest
pipeline. Each client has a `test_connection()` method so the Settings UI
can verify connectivity without firing real pipeline jobs.

Higher-level routing (OpenKVK primary, KVK fallback) lives at the bottom
of this file in `KvkSourceRouter`. Pipeline modules should always call
the router, never the raw clients directly, so the operator can swap
which source is in use via the Settings toggle.

Sources implemented:
  * OpenKVK (overheid.io)   -- free Dutch chamber-of-commerce lookups (primary)
  * KVK official API        -- paid but official; fallback when OpenKVK is off
  * PDOK Locatieserver      -- free Dutch geocoder
  * crt.sh                  -- free Certificate Transparency search
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from salespilot.models.integrations import Integration


@dataclass
class SourceTestResult:
    ok: bool
    detail: str
    sample: dict[str, Any] | None = None


@dataclass
class CompanyResult:
    """Normalised company record. Returned by both OpenKVK and KVK
    clients so the router can present the same shape to the pipeline.
    """
    kvk_number: str
    name: str
    trade_name: str | None = None
    legal_form: str | None = None
    street: str | None = None
    house_number: str | None = None
    postal_code: str | None = None
    city: str | None = None
    country: str | None = None
    website: str | None = None
    sbi_codes: list[str] = field(default_factory=list)
    sbi_descriptions: list[str] = field(default_factory=list)
    employees: int | None = None
    is_main_establishment: bool | None = None
    source: Literal["openkvk", "kvk"] = "openkvk"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class FunctionarisResult:
    """Decision-maker / board member."""
    full_name: str
    title: str | None = None
    role: str | None = None
    source: Literal["openkvk", "kvk"] = "openkvk"
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# OpenKVK / overheid.io
# ---------------------------------------------------------------------------


class OpenKvkClient:
    """OpenKVK via overheid.io. Most endpoints work without API key but
    are rate-limited. A free ovio-api-key raises the limit substantially.
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
            r = await c.get(self.base_url, params={"size": "1"}, headers=self._headers())
            if r.status_code == 401:
                return SourceTestResult(ok=False, detail="API-key ongeldig of vereist.")
            if r.status_code == 429:
                return SourceTestResult(ok=False, detail="Rate-limit bereikt. Voeg een gratis API-key toe.")
            if r.is_success:
                data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                items = (data.get("_embedded") or {}).get("rechtspersoon", []) if isinstance(data, dict) else []
                return SourceTestResult(
                    ok=True,
                    detail=f"OpenKVK bereikbaar ({r.status_code}). Sample retourneerde {len(items)} item.",
                    sample=items[0] if items else None,
                )
            return SourceTestResult(ok=False, detail=f"OpenKVK gaf status {r.status_code}: {r.text[:120]}")

    async def lookup_by_kvk(self, kvk_number: str) -> CompanyResult | None:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(f"{self.base_url}/{kvk_number}", headers=self._headers())
            if r.status_code == 404 or not r.is_success:
                return None
            return self._to_company(r.json())

    async def search(self, query: str, city: str | None = None, size: int = 20) -> list[CompanyResult]:
        params: dict[str, str] = {"size": str(size)}
        if query:
            params["queryFields[handelsnaam]"] = query
        if city:
            params["queryFields[plaats]"] = city
        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.get(self.base_url, params=params, headers=self._headers())
            if not r.is_success:
                return []
            data = r.json() or {}
            items = (data.get("_embedded") or {}).get("rechtspersoon", []) or []
            return [self._to_company(x) for x in items if isinstance(x, dict)]

    async def list_functionarissen(self, kvk_number: str) -> list[FunctionarisResult]:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(f"{self.base_url}/{kvk_number}/functionarissen", headers=self._headers())
            if not r.is_success:
                return []
            data = r.json() or {}
            items = (data.get("_embedded") or {}).get("functionaris", []) or []
            out: list[FunctionarisResult] = []
            for f in items:
                if not isinstance(f, dict):
                    continue
                given = f.get("voornaam") or ""
                middle = f.get("tussenvoegsel") or ""
                family = f.get("achternaam") or f.get("geslachtsnaam") or ""
                full = " ".join(p for p in [given, middle, family] if p).strip() or f.get("naam") or "(onbekend)"
                out.append(FunctionarisResult(
                    full_name=full, title=f.get("functie"), role=f.get("type"),
                    source="openkvk", raw=f,
                ))
            return out

    @staticmethod
    def _to_company(d: dict[str, Any]) -> CompanyResult:
        kvk = str(d.get("dossiernummer") or d.get("kvkNummer") or "").strip()
        acts = d.get("activiteit") or d.get("activiteiten") or []
        if isinstance(acts, dict):
            acts = [acts]
        sbi_codes = [str(a.get("sbi")) for a in acts if isinstance(a, dict) and a.get("sbi")]
        sbi_desc = [str(a.get("omschrijving")) for a in acts if isinstance(a, dict) and a.get("omschrijving")]
        return CompanyResult(
            kvk_number=kvk,
            name=d.get("handelsnaam") or d.get("statutaire_naam") or "(onbekend)",
            trade_name=d.get("handelsnaam"),
            legal_form=d.get("rechtsvorm"),
            street=d.get("straat") or d.get("straatnaam"),
            house_number=str(d.get("huisnummer") or "") or None,
            postal_code=d.get("postcode"),
            city=d.get("plaats"),
            country=d.get("land") or "Nederland",
            website=d.get("internetadres") or d.get("website"),
            sbi_codes=sbi_codes,
            sbi_descriptions=sbi_desc,
            source="openkvk",
            raw=d,
        )


# ---------------------------------------------------------------------------
# KVK official API
# ---------------------------------------------------------------------------


class KvkClient:
    """Official KVK API (https://developers.kvk.nl)."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 functionarissen_key: str | None = None) -> None:
        self.base_url = (base_url or "https://api.kvk.nl/api").rstrip("/")
        self.api_key = api_key
        self.functionarissen_key = functionarissen_key

    async def test_connection(self) -> SourceTestResult:
        if not self.api_key:
            return SourceTestResult(ok=False, detail="KVK basisprofiel API-key ontbreekt.")
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(
                f"{self.base_url}/v2/zoeken",
                params={"kvkNummer": "27312152"},
                headers={"apikey": self.api_key, "Accept": "application/json"},
            )
            if r.status_code in (401, 403):
                return SourceTestResult(ok=False, detail=f"KVK weigerde de key (HTTP {r.status_code}).")
            if r.is_success:
                data = r.json()
                count = len((data or {}).get("resultaten") or [])
                detail = f"KVK basisprofiel bereikbaar. Sample retourneerde {count} resultaten."
                if self.functionarissen_key:
                    fr = await c.get(
                        f"{self.base_url}/v1/basisprofielen/27312152/functionarissen",
                        headers={"apikey": self.functionarissen_key, "Accept": "application/json"},
                    )
                    detail += " Functionarissen-key OK." if fr.is_success else f" Functionarissen-key faalde ({fr.status_code})."
                return SourceTestResult(ok=True, detail=detail)
            return SourceTestResult(ok=False, detail=f"KVK gaf status {r.status_code}: {r.text[:120]}")

    async def lookup_by_kvk(self, kvk_number: str) -> CompanyResult | None:
        if not self.api_key:
            return None
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(
                f"{self.base_url}/v1/basisprofielen/{kvk_number}",
                headers={"apikey": self.api_key, "Accept": "application/json"},
            )
            if r.status_code == 404 or not r.is_success:
                return None
            return self._to_company(r.json())

    async def search(self, query: str, city: str | None = None, size: int = 20) -> list[CompanyResult]:
        if not self.api_key:
            return []
        params: dict[str, str] = {"resultatenPerPagina": str(size)}
        if query:
            params["handelsnaam"] = query
        if city:
            params["plaats"] = city
        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.get(
                f"{self.base_url}/v2/zoeken", params=params,
                headers={"apikey": self.api_key, "Accept": "application/json"},
            )
            if not r.is_success:
                return []
            data = r.json() or {}
            items = data.get("resultaten") or []
            out: list[CompanyResult] = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                kvk = str(it.get("kvkNummer") or "").strip()
                if not kvk:
                    continue
                detail = await self.lookup_by_kvk(kvk)
                if detail is not None:
                    out.append(detail)
            return out

    async def list_functionarissen(self, kvk_number: str) -> list[FunctionarisResult]:
        key = self.functionarissen_key or self.api_key
        if not key:
            return []
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(
                f"{self.base_url}/v1/basisprofielen/{kvk_number}/functionarissen",
                headers={"apikey": key, "Accept": "application/json"},
            )
            if not r.is_success:
                return []
            data = r.json() or {}
            items = data.get("functionarissen") or data.get("eigenaars") or []
            out: list[FunctionarisResult] = []
            for f in items:
                if not isinstance(f, dict):
                    continue
                naam = f.get("naamgegevens") or f
                given = naam.get("voornamen") or ""
                middle = naam.get("voorvoegselGeslachtsnaam") or ""
                family = naam.get("geslachtsnaam") or ""
                full = " ".join(p for p in [given, middle, family] if p).strip() or naam.get("volledigeNaam") or "(onbekend)"
                out.append(FunctionarisResult(
                    full_name=full, title=f.get("functie") or f.get("functieTitel"),
                    role=f.get("type") or f.get("functieRol"), source="kvk", raw=f,
                ))
            return out

    @staticmethod
    def _to_company(d: dict[str, Any]) -> CompanyResult:
        emb = d.get("_embedded") or {}
        hoofd = emb.get("hoofdvestiging") or {}
        adressen = hoofd.get("adressen") or []
        adr = next((a for a in adressen if a.get("type") == "bezoekadres"),
                   adressen[0] if adressen else {})
        sbis = hoofd.get("sbiActiviteiten") or []
        websites = hoofd.get("websites") or []
        handelsnamen = d.get("handelsnamen") or []
        trade = handelsnamen[0].get("naam") if (handelsnamen and isinstance(handelsnamen[0], dict)) else None
        return CompanyResult(
            kvk_number=str(d.get("kvkNummer") or ""),
            name=d.get("naam") or trade or "(onbekend)",
            trade_name=trade,
            legal_form=hoofd.get("rechtsvorm") or d.get("rechtsvorm"),
            street=adr.get("straatnaam"),
            house_number=str(adr.get("huisnummer") or "") or None,
            postal_code=adr.get("postcode"),
            city=adr.get("plaats"),
            country=adr.get("land") or "Nederland",
            website=websites[0] if websites else None,
            sbi_codes=[str(s.get("sbiCode")) for s in sbis if isinstance(s, dict) and s.get("sbiCode")],
            sbi_descriptions=[str(s.get("sbiOmschrijving")) for s in sbis if isinstance(s, dict) and s.get("sbiOmschrijving")],
            is_main_establishment=True,
            source="kvk",
            raw=d,
        )


# ---------------------------------------------------------------------------
# PDOK Locatieserver
# ---------------------------------------------------------------------------


class PdokClient:
    """PDOK Locatieserver -- free Dutch geocoder."""

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
                docs = (r.json().get("response") or {}).get("docs") or []
                return SourceTestResult(
                    ok=True, detail=f"PDOK Locatieserver bereikbaar ({r.status_code}).",
                    sample=docs[0] if docs else None,
                )
            return SourceTestResult(ok=False, detail=f"PDOK gaf status {r.status_code}: {r.text[:120]}")

    async def geocode_address(self, query: str) -> tuple[float, float] | None:
        """Free-form address -> (lat, lon)."""
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(
                f"{self.base_url}/bzk/locatieserver/search/v3_1/free",
                params={"q": query, "rows": "1", "fl": "centroide_ll,weergavenaam"},
                headers={"Accept": "application/json"},
            )
            if not r.is_success:
                return None
            docs = ((r.json() or {}).get("response") or {}).get("docs") or []
            if not docs:
                return None
            point = docs[0].get("centroide_ll") or ""
            m = re.match(r"POINT\(([-\d.]+)\s+([-\d.]+)\)", point)
            if not m:
                return None
            return (float(m.group(2)), float(m.group(1)))  # (lat, lon)


# ---------------------------------------------------------------------------
# crt.sh
# ---------------------------------------------------------------------------


class CrtShClient:
    """crt.sh -- Certificate Transparency log search."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or "https://crt.sh").rstrip("/")

    async def test_connection(self) -> SourceTestResult:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(self.base_url, params={"q": "%.nl", "output": "json"})
            if r.is_success:
                try:
                    count = len(r.json()) if isinstance(r.json(), list) else 0
                except Exception:
                    count = 0
                return SourceTestResult(
                    ok=True,
                    detail=f"crt.sh bereikbaar. Sample {count} certificaten.",
                )
            return SourceTestResult(ok=False, detail=f"crt.sh gaf status {r.status_code}")

    async def find_subdomains(self, root_domain: str) -> set[str]:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.get(
                self.base_url, params={"q": f"%.{root_domain}", "output": "json"},
                headers={"Accept": "application/json"},
            )
            if not r.is_success:
                return set()
            try:
                rows = r.json()
            except Exception:
                return set()
            out: set[str] = set()
            for row in rows or []:
                name = (row.get("name_value") or "").strip()
                for part in name.split("\n"):
                    part = part.strip().lower()
                    if part.endswith(root_domain.lower()) and "*" not in part:
                        out.add(part)
            return out


# ---------------------------------------------------------------------------
# Router -- OpenKVK primary, KVK fallback
# ---------------------------------------------------------------------------


@dataclass
class KvkSourceRouter:
    """Pick the right Dutch chamber-of-commerce source for this org.

    Priority is fixed: OpenKVK first (free, sufficient for our scale),
    and the official KVK API as automatic fallback IF the user has it
    configured AND enabled. If only one is configured/enabled, we use
    that one. If neither, we still construct an unauthenticated
    OpenKVK client so the pipeline keeps working (rate-limited).

    `from_org(db, org_id)` is the canonical constructor.
    """

    openkvk: OpenKvkClient | None = None
    kvk: KvkClient | None = None

    @classmethod
    async def from_org(cls, db: AsyncSession, org_id: Any) -> "KvkSourceRouter":
        rows = (
            await db.execute(
                select(Integration).where(Integration.kind.in_(["openkvk", "kvk"]))
            )
        ).scalars().all()

        openkvk: OpenKvkClient | None = None
        kvk: KvkClient | None = None
        for r in rows:
            cfg = r.config_json or {}
            if not r.is_enabled:
                continue
            if r.kind == "openkvk":
                openkvk = OpenKvkClient(
                    base_url=cfg.get("base_url") or None,
                    api_key=cfg.get("api_key") or None,
                )
            elif r.kind == "kvk" and cfg.get("api_key"):
                kvk = KvkClient(
                    base_url=cfg.get("base_url") or None,
                    api_key=cfg.get("api_key"),
                    functionarissen_key=cfg.get("functionarissen_api_key"),
                )

        # Always have at least OpenKVK available so the pipeline doesn't
        # silently noop on a fresh install.
        if openkvk is None and kvk is None:
            openkvk = OpenKvkClient()

        return cls(openkvk=openkvk, kvk=kvk)

    @property
    def primary_label(self) -> str:
        if self.openkvk is not None:
            return "openkvk"
        if self.kvk is not None:
            return "kvk"
        return "none"

    async def lookup_by_kvk(self, kvk_number: str) -> CompanyResult | None:
        """Try OpenKVK first; on miss/error, fall back to KVK."""
        if self.openkvk is not None:
            try:
                hit = await self.openkvk.lookup_by_kvk(kvk_number)
                if hit is not None:
                    return hit
            except Exception:
                pass
        if self.kvk is not None:
            try:
                return await self.kvk.lookup_by_kvk(kvk_number)
            except Exception:
                return None
        return None

    async def search(self, query: str, city: str | None = None, size: int = 20) -> list[CompanyResult]:
        if self.openkvk is not None:
            try:
                hits = await self.openkvk.search(query, city=city, size=size)
                if hits:
                    return hits
            except Exception:
                pass
        if self.kvk is not None:
            try:
                return await self.kvk.search(query, city=city, size=size)
            except Exception:
                return []
        return []

    async def list_functionarissen(self, kvk_number: str) -> list[FunctionarisResult]:
        """KVK official is authoritative for board members; we prefer it
        when configured, then fill in extras from OpenKVK."""
        out: list[FunctionarisResult] = []
        seen: set[str] = set()
        if self.kvk is not None:
            try:
                for f in await self.kvk.list_functionarissen(kvk_number):
                    key = f.full_name.lower()
                    if key not in seen:
                        out.append(f)
                        seen.add(key)
            except Exception:
                pass
        if self.openkvk is not None:
            try:
                for f in await self.openkvk.list_functionarissen(kvk_number):
                    key = f.full_name.lower()
                    if key not in seen:
                        out.append(f)
                        seen.add(key)
            except Exception:
                pass
        return out
