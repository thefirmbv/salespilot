"""Async SnelStart 12 (cloud) REST client.

SnelStart's B2B API uses OAuth2 client_credentials *with* an Ocp-Apim-
Subscription-Key header for rate limiting on Azure API Management.

Auth flow:
    POST https://auth.snelstart.nl/b2b/token
        Content-Type: application/x-www-form-urlencoded
        body: grant_type=client_credentials
              &client_id={client_id}
              &client_secret={client_secret}
              &scope=snelstart-api

    Response: { access_token, expires_in, token_type }

Resource endpoints (default base: https://b2bapi.snelstart.nl/v2):
    GET    /administraties                     -- list administrations
    GET    /administraties/{id}                -- single administration

Each call below requires the administration ID in the URL or as query.
We treat one Integration row as 'one tenant + one default administration'.

    GET    /relaties?administratieId={a}
    GET    /verkoopfacturen?administratieId={a}&from=&to=
    GET    /verkoopfacturen/{id}
    PUT    /verkoopfacturen/{id}               -- update (e.g., toggle SEPA flag)
    POST   /verkoopfacturen
    GET    /incassomachtigingen
    GET    /groepen                            -- 'Groepen' aggregation buckets
    GET    /grootboeken                        -- ledger accounts

SEPA flag on a sales invoice is the boolean ``isIncasso`` (sometimes
``incasso``). HaloPSA's invoice export to SnelStart doesn't always set
this when a SEPA mandate exists on the customer, which is the bulk-fix
problem this client solves.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

import httpx
from pydantic import BaseModel, Field


class SnelStartError(Exception):
    """Any non-2xx response, or a token-acquire failure."""


class SnelStartCredentials(BaseModel):
    """Per-tenant credentials. Loaded from Integration.config_json.

    Naming follows SnelStart's developer portal exactly so users can
    paste values without renaming.
    """

    subscription_key: str = Field(..., description="Ocp-Apim-Subscription-Key from developer.snelstart.nl")
    client_id: str
    client_secret: str
    # The active administration. SnelStart customers can have multiple,
    # but our integration runs against one at a time. Stored as UUID
    # string; switching is a config change, not a per-request decision.
    administratie_id: str | None = None
    base_url: str = "https://b2bapi.snelstart.nl"
    token_url: str = "https://auth.snelstart.nl/b2b/token"
    scope: str = "snelstart-api"


def _normalize_base(url: str) -> str:
    u = url.strip().rstrip("/")
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u


def _relatie_id_of(snelstart_obj: dict) -> str | None:
    """Pak relatie-id uit een Snelstart object dat een 'relatie'-veld heeft.

    Werkt voor zowel embedded ({"id":"...", "uri":"..."}) als flat
    (alleen 'relatieId' / 'RelatieId') varianten.
    """
    rel = snelstart_obj.get("relatie")
    if isinstance(rel, dict):
        return rel.get("id")
    if isinstance(rel, str):
        return rel
    return snelstart_obj.get("relatieId") or snelstart_obj.get("RelatieId")


class SnelStartClient:
    """One client per tenant per call-site. Re-uses the token within
    its own lifetime; pool nothing across instances.
    """

    def __init__(self, creds: SnelStartCredentials, timeout_s: float = 30.0) -> None:
        self.creds = creds
        self.base = _normalize_base(creds.base_url)
        self.token_url = creds.token_url
        self._token: str | None = None
        self._token_expires_at: datetime | None = None
        self._client = httpx.AsyncClient(timeout=timeout_s)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "SnelStartClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def _ensure_token(self) -> str:
        """Fetch a new bearer token if we don't have one or it's expired
        (with a 60s safety margin)."""
        now = datetime.now(UTC)
        if (
            self._token
            and self._token_expires_at
            and now < self._token_expires_at - timedelta(seconds=60)
        ):
            return self._token

        try:
            res = await self._client.post(
                self.token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.creds.client_id,
                    "client_secret": self.creds.client_secret,
                    "scope": self.creds.scope,
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            )
        except httpx.HTTPError as e:
            raise SnelStartError(f"Token request failed: {e}") from e

        if res.status_code != 200:
            raise SnelStartError(
                f"Token request returned {res.status_code}: {res.text[:300]}"
            )

        body = res.json()
        token = body.get("access_token")
        expires_in = int(body.get("expires_in") or 3600)
        if not token:
            raise SnelStartError(
                f"Token response had no access_token: {body!r}"
            )
        self._token = token
        self._token_expires_at = now + timedelta(seconds=expires_in)
        return token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        """Authenticated request. ``path`` may be absolute or relative
        (we prepend base + /v2 for relative paths)."""
        token = await self._ensure_token()
        if path.startswith("http"):
            url = path
        else:
            # Relative paths get /v2 prefix unless they already have a version
            if not path.startswith("/v"):
                path = "/v2" + (path if path.startswith("/") else "/" + path)
            url = f"{self.base}{path}"

        headers = {
            "Authorization": f"Bearer {token}",
            "Ocp-Apim-Subscription-Key": self.creds.subscription_key,
            "Accept": "application/json",
        }
        if json is not None:
            headers["Content-Type"] = "application/json"

        try:
            res = await self._client.request(
                method, url, headers=headers, params=params, json=json,
            )
        except httpx.HTTPError as e:
            raise SnelStartError(f"{method} {path} failed: {e}") from e

        if res.status_code == 401:
            # Token may have been revoked mid-flight; force a refresh
            # once. Subsequent 401s are a real auth problem.
            self._token = None
            raise SnelStartError(
                f"{method} {path} returned 401: invalid credentials"
            )
        if res.status_code == 403:
            raise SnelStartError(
                f"{method} {path} returned 403: missing scope or subscription"
            )
        if res.status_code == 429:
            raise SnelStartError(
                f"{method} {path} returned 429: rate-limited, retry later"
            )
        if res.status_code >= 400:
            raise SnelStartError(
                f"{method} {path} returned {res.status_code}: {res.text[:500]}"
            )

        if not res.content:
            return None
        # Some PUT endpoints return 204 No Content
        try:
            return res.json()
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Administraties (top-level entity, required for everything else)
    # ------------------------------------------------------------------

    async def list_administraties(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/administraties")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("results") or data.get("items") or []
        return []

    # ------------------------------------------------------------------
    # Relaties (customers)
    # ------------------------------------------------------------------

    async def list_relaties(
        self, top: int = 100, skip: int = 0,
    ) -> list[dict[str, Any]]:
        params = {"$top": top, "$skip": skip}
        data = await self._request("GET", "/relaties", params=params)
        return data if isinstance(data, list) else (data.get("results", []) if isinstance(data, dict) else [])

    async def get_relatie(self, relatie_id: str) -> dict[str, Any] | None:
        return await self._request("GET", f"/relaties/{relatie_id}")

    # ------------------------------------------------------------------
    # Groepen (group aggregation buckets, used for Financieel dashboard)
    # ------------------------------------------------------------------

    async def list_groepen(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/groepen")
        return data if isinstance(data, list) else (data.get("results", []) if isinstance(data, dict) else [])

    # ------------------------------------------------------------------
    # Verkoopfacturen (sales invoices) -- core for SEPA fix + dashboard
    # ------------------------------------------------------------------

    async def list_verkoopfacturen(
        self,
        *,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        top: int = 100,
        skip: int = 0,
        filter_expr: str | None = None,
    ) -> list[dict[str, Any]]:
        """List sales invoices, optionally bounded by datum range.

        SnelStart uses OData-style $filter; the simplest range filter is
        ``Factuurdatum ge 2026-01-01 and Factuurdatum le 2026-04-30``.
        """
        params: dict[str, Any] = {"$top": top, "$skip": skip}
        parts: list[str] = []
        if from_date is not None:
            parts.append(f"Factuurdatum ge {from_date.date().isoformat()}")
        if to_date is not None:
            parts.append(f"Factuurdatum le {to_date.date().isoformat()}")
        if filter_expr:
            parts.append(filter_expr)
        if parts:
            params["$filter"] = " and ".join(parts)
        data = await self._request("GET", "/verkoopfacturen", params=params)
        return data if isinstance(data, list) else (data.get("results", []) if isinstance(data, dict) else [])

    async def get_verkoopfactuur(self, factuur_id: str) -> dict[str, Any] | None:
        return await self._request("GET", f"/verkoopfacturen/{factuur_id}")

    async def update_verkoopfactuur(
        self, factuur_id: str, patch: dict[str, Any],
    ) -> dict[str, Any] | None:
        """PUT a partial update. We use this to toggle isIncasso=True for
        the SEPA bulk-fix. ``patch`` must include every field SnelStart
        expects, so callers typically GET first, mutate, then PUT.
        """
        return await self._request(
            "PUT", f"/verkoopfacturen/{factuur_id}", json=patch,
        )

    # ------------------------------------------------------------------
    # Incassomachtigingen (SEPA mandates)
    # ------------------------------------------------------------------

    async def list_incassomachtigingen(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/incassomachtigingen")
        return data if isinstance(data, list) else (data.get("results", []) if isinstance(data, dict) else [])

    async def list_incassomachtigingen_for_relatie(
        self, relatie_id: str,
    ) -> list[dict[str, Any]]:
        """Filtered: alleen machtigingen van één relatie.

        We gebruiken het OData $filter zodat we niet alle machtigingen
        van alle klanten hoeven op te halen. Snelstart accepteert
        ``relatie/id eq guid'<id>'`` als filter.
        """
        params = {
            "$filter": f"relatie/id eq guid'{relatie_id}'",
            "$top": 200,
        }
        try:
            data = await self._request("GET", "/incassomachtigingen", params=params)
        except SnelStartError:
            # Sommige tenants accepteren de OData syntax niet. Fallback:
            # haal alles op en filter client-side.
            all_machtigingen = await self.list_incassomachtigingen()
            return [
                m for m in all_machtigingen
                if str(_relatie_id_of(m) or "") == str(relatie_id)
            ]
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("results", []) or []
        return []

    async def create_incassomachtiging(
        self,
        *,
        relatie_id: str,
        kenmerk: str,
        machtiging_datum: datetime,
        soort: str = "Doorlopend",
        sequencetype: str = "Eerste",
        omschrijving: str = "",
    ) -> dict[str, Any]:
        """Maak een doorlopende incassomachtiging aan voor een relatie.

        Snelstart-veldnamen volgens hun B2B API model:
          - relatie: { id, uri }
          - kenmerk: uniek (= onze UMR)
          - machtigingDatum: ISO datetime
          - soort: 'Doorlopend' of 'Eenmalig'
          - sequenceType: 'Eerste' bij nieuwe machtiging, daarna 'Volgende'

        Veldnamen zijn camelCase in v2 API. Bij onzekerheid: probeer
        eerst zonder optionele velden.
        """
        body = {
            "relatie": {"id": relatie_id},
            "kenmerk": kenmerk[:50],  # Snelstart max 50 chars
            "machtigingDatum": machtiging_datum.isoformat(),
            "soort": soort,
            "sequenceType": sequencetype,
        }
        if omschrijving:
            body["omschrijving"] = omschrijving[:50]
        return await self._request("POST", "/incassomachtigingen", json=body)

    async def update_relatie_incasso_settings(
        self,
        relatie_id: str,
        *,
        incasso_soort: str = "Standaard",
        iban: str | None = None,
        bic: str | None = None,
    ) -> dict[str, Any] | None:
        """Zet incasso-contract op de klant.

        Snelstart vereist dat de klant in de relatie-kaart als
        'Standaard (CORE)' of 'Zakelijk (B2B)' is geconfigureerd
        voordat machtigingen werken. Default: Standaard (CORE).
        """
        # We GET eerst de volledige relatie, mutate, dan PUT (Snelstart
        # vereist een volledige body bij PUT).
        full = await self.get_relatie(relatie_id)
        if not full:
            raise SnelStartError(f"Relatie {relatie_id} niet gevonden")
        full["incasso"] = incasso_soort
        if iban:
            full["iban"] = iban
        if bic:
            full["bic"] = bic
        return await self._request("PUT", f"/relaties/{relatie_id}", json=full)

    # ------------------------------------------------------------------
    # Verkoopboekingen (v2 -- de echte resource die HaloPSA pusht)
    # ------------------------------------------------------------------

    async def list_verkoopboekingen(
        self,
        *,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        top: int = 100,
        skip: int = 0,
        filter_expr: str | None = None,
    ) -> list[dict[str, Any]]:
        """Lijst verkoopboekingen. Resource heet ``/verkoopboekingen``
        in v2 (cfr. https://b2bapi-developer.snelstart.nl).

        Field ``doorlopendeIncassoMachtiging`` zit hierop -- de bestaande
        ``/verkoopfacturen``-resource is een ander/oudere endpoint.
        """
        params: dict[str, Any] = {"$top": top, "$skip": skip}
        parts: list[str] = []
        if from_date is not None:
            parts.append(f"factuurdatum ge {from_date.date().isoformat()}")
        if to_date is not None:
            parts.append(f"factuurdatum le {to_date.date().isoformat()}")
        if filter_expr:
            parts.append(filter_expr)
        if parts:
            params["$filter"] = " and ".join(parts)
        data = await self._request("GET", "/verkoopboekingen", params=params)
        return data if isinstance(data, list) else (
            data.get("results", []) if isinstance(data, dict) else []
        )

    async def get_verkoopboeking(self, boeking_id: str) -> dict[str, Any] | None:
        return await self._request("GET", f"/verkoopboekingen/{boeking_id}")

    async def update_verkoopboeking(
        self, boeking_id: str, body: dict[str, Any],
    ) -> dict[str, Any] | None:
        """PUT volledige verkoopboeking. Snelstart staat geen PATCH toe;
        callers moeten GET + mutate + PUT doen."""
        return await self._request(
            "PUT", f"/verkoopboekingen/{boeking_id}", json=body,
        )

    # ------------------------------------------------------------------
    # Convenience: test
    # ------------------------------------------------------------------

    async def test_connection(self) -> dict[str, Any]:
        """Cheapest call that proves auth + subscription work."""
        admins = await self.list_administraties()
        return {
            "ok": True,
            "administraties_count": len(admins),
            "administraties": [
                {"id": a.get("id"), "naam": a.get("naam") or a.get("name")}
                for a in admins[:10]
            ],
        }
