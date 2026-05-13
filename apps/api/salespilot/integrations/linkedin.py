"""LinkedIn API client + publisher.

Implements the bits of the LinkedIn API that we need for the social
scheduler:

  * Listing the authenticated user's permitted destinations
    (their own person URN, plus organizations they admin)
  * Uploading media (images for now; video later)
  * Publishing a post (text-only, single image, or carousel)
  * Reading analytics for a published post

The integration stores config_json under kind='linkedin' with:
  access_token, refresh_token, person_urn, organization_urn (optional)

We don't implement the OAuth dance here -- that lives in
api/integrations.py and is wired up in a future session. For now the
user pastes an access token (LinkedIn lets you generate one in their
developer console for testing) and we use it.

LinkedIn API gotchas this client handles:
  * /me returns 'sub' for OpenID Connect-style tokens or 'id' for older
    r_basicprofile tokens
  * Post creation uses the new /rest/posts endpoint with header
    LinkedIn-Version: YYYYMM
  * Image upload is a two-step register-then-PUT-binary dance
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx


LI_API_BASE = "https://api.linkedin.com"
LI_REST_VERSION = "202404"  # LinkedIn requires a YYYYMM version header


@dataclass
class LinkedInPostResult:
    ok: bool
    platform_post_id: str | None = None
    post_url: str | None = None
    error: str | None = None
    raw: dict[str, Any] | None = None


class LinkedInError(Exception):
    pass


class LinkedInClient:
    """Async LinkedIn API client. One instance per (access_token).

    Use as an async context manager so the underlying httpx client is
    properly closed.
    """

    def __init__(self, access_token: str) -> None:
        self.access_token = access_token
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "LinkedInClient":
        self._http = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            raise RuntimeError("LinkedInClient must be used as async context manager")
        return self._http

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": LI_REST_VERSION,
        }
        if extra:
            h.update(extra)
        return h

    # ----- Identity -----

    async def get_me(self) -> dict[str, Any]:
        """Fetch the authenticated user's profile. Returns dict with at
        minimum 'urn' (e.g. 'urn:li:person:XYZ') and 'name'."""
        r = await self.http.get(f"{LI_API_BASE}/v2/userinfo", headers=self._headers())
        if r.status_code == 401:
            raise LinkedInError("LinkedIn token expired or invalid")
        if not r.is_success:
            raise LinkedInError(f"GET /v2/userinfo {r.status_code}: {r.text[:200]}")
        data = r.json()
        # OpenID Connect: data['sub'] is the user id
        sub = data.get("sub") or data.get("id")
        name = data.get("name") or " ".join(
            p for p in [data.get("given_name"), data.get("family_name")] if p
        ).strip() or "(LinkedIn user)"
        return {
            "urn": f"urn:li:person:{sub}",
            "name": name,
            "email": data.get("email"),
            "raw": data,
        }

    async def list_admin_organizations(self) -> list[dict[str, Any]]:
        """Return organizations the authenticated user can post for.

        Requires the r_organization_admin scope. If the user only has
        personal-profile access this returns []. We do best-effort and
        swallow 403.
        """
        # Step 1: which organization-acls does the user have?
        r = await self.http.get(
            f"{LI_API_BASE}/v2/organizationAcls",
            params={"q": "roleAssignee", "role": "ADMINISTRATOR", "state": "APPROVED"},
            headers=self._headers(),
        )
        if r.status_code == 403:
            return []
        if not r.is_success:
            return []  # silent — most users won't have org access
        elements = (r.json() or {}).get("elements") or []
        org_urns = [e.get("organization") for e in elements if e.get("organization")]
        if not org_urns:
            return []

        # Step 2: look up org names
        out: list[dict[str, Any]] = []
        for urn in org_urns:
            org_id = urn.rsplit(":", 1)[-1]
            rr = await self.http.get(
                f"{LI_API_BASE}/v2/organizations/{org_id}",
                headers=self._headers(),
            )
            if rr.is_success:
                d = rr.json() or {}
                # localizedName lives under d['localizedName']
                name = d.get("localizedName") or d.get("name") or f"Organization {org_id}"
                out.append({"urn": urn, "name": name, "raw": d})
        return out

    # ----- Media upload -----

    async def upload_image(self, owner_urn: str, file_bytes: bytes, mime_type: str) -> str:
        """Upload an image and return its LinkedIn asset URN, ready to
        embed in a post.

        owner_urn must be either the person or organization URN that will
        author the post.
        """
        # Step 1: initialize the upload
        init = await self.http.post(
            f"{LI_API_BASE}/rest/images",
            params={"action": "initializeUpload"},
            json={"initializeUploadRequest": {"owner": owner_urn}},
            headers=self._headers({"Content-Type": "application/json"}),
        )
        if not init.is_success:
            raise LinkedInError(
                f"initializeUpload {init.status_code}: {init.text[:200]}"
            )
        data = (init.json() or {}).get("value") or {}
        upload_url = data.get("uploadUrl")
        asset_urn = data.get("image")
        if not upload_url or not asset_urn:
            raise LinkedInError(f"initializeUpload missing fields: {data}")

        # Step 2: PUT the binary to the returned uploadUrl. LinkedIn does
        # NOT want the Authorization header on this URL.
        async with httpx.AsyncClient(timeout=60.0) as raw:
            put = await raw.put(
                upload_url,
                content=file_bytes,
                headers={"Content-Type": mime_type or "application/octet-stream"},
            )
            if not put.is_success:
                raise LinkedInError(f"upload PUT {put.status_code}: {put.text[:200]}")

        return asset_urn

    # ----- Post creation -----

    async def create_post(
        self,
        *,
        author_urn: str,
        commentary: str,
        image_urns: list[str] | None = None,
        visibility: str = "PUBLIC",
    ) -> LinkedInPostResult:
        """Create a UGC post (text-only or with one+ images).

        Returns LinkedInPostResult including the new post URN and a
        public post URL.
        """
        media_block: dict[str, Any] = {}
        if image_urns:
            if len(image_urns) == 1:
                media_block = {"media": {"id": image_urns[0]}}
            else:
                media_block = {
                    "multiImage": {
                        "images": [{"id": u} for u in image_urns],
                    }
                }

        payload: dict[str, Any] = {
            "author": author_urn,
            "commentary": commentary,
            "visibility": visibility,
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        if media_block:
            payload["content"] = media_block

        r = await self.http.post(
            f"{LI_API_BASE}/rest/posts",
            json=payload,
            headers=self._headers({"Content-Type": "application/json"}),
        )
        if r.status_code in (200, 201):
            # The post URN comes back in the x-restli-id header
            post_urn = r.headers.get("x-restli-id") or r.headers.get("x-linkedin-id")
            url = None
            if post_urn:
                # urn:li:share:1234567 or urn:li:ugcPost:123 -> activity URL
                tail = post_urn.rsplit(":", 1)[-1]
                url = f"https://www.linkedin.com/feed/update/{post_urn}"
                if "share" in post_urn:
                    url = f"https://www.linkedin.com/feed/update/urn:li:share:{tail}"
            return LinkedInPostResult(
                ok=True,
                platform_post_id=post_urn,
                post_url=url,
                raw=r.json() if r.content else None,
            )
        return LinkedInPostResult(
            ok=False,
            error=f"HTTP {r.status_code}: {r.text[:300]}",
        )

    # ----- Analytics -----

    async def get_post_stats(self, post_urn: str) -> dict[str, Any]:
        """Best-effort fetch of social-actions counters. LinkedIn's full
        analytics endpoint requires special partner access; here we use
        the publicly available socialActions counts (likes, comments)."""
        out: dict[str, Any] = {}
        try:
            r = await self.http.get(
                f"{LI_API_BASE}/v2/socialActions/{post_urn}",
                headers=self._headers(),
            )
            if r.is_success:
                d = r.json() or {}
                out["likes"] = (d.get("likesSummary") or {}).get("totalLikes", 0)
                out["comments"] = (d.get("commentsSummary") or {}).get("totalFirstLevelComments", 0)
        except Exception:
            pass
        # Impressions require Marketing Developer Platform access -- we
        # leave them at 0 for now.
        out.setdefault("impressions", 0)
        out.setdefault("shares", 0)
        out.setdefault("clicks", 0)
        return out


async def list_destinations_for_token(access_token: str) -> list[dict[str, Any]]:
    """Convenience: return all destinations the user can post to."""
    async with LinkedInClient(access_token) as li:
        me = await li.get_me()
        out = [
            {
                "target_type": "person",
                "target_urn": me["urn"],
                "target_name": me["name"],
            }
        ]
        for org in await li.list_admin_organizations():
            out.append(
                {
                    "target_type": "organization",
                    "target_urn": org["urn"],
                    "target_name": org["name"],
                }
            )
        return out
