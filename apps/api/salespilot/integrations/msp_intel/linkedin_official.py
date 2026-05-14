"""LinkedIn customer-discovery via the official Marketing Developer Platform.

This module is a STUB until IT-Gemak's LinkedIn Marketing Developer
Platform approval lands (~2-3 weeks after applying). When that happens
we'll use the Organizational Entity Lookup + UGC Posts API to:

  1) For a given MSP organization URN, list the recent organic posts
     (their announcements feed).
  2) AI-classify which posts announce a new customer relationship.
  3) Extract the customer organisation name + match it against the
     LinkedIn Company API for an authoritative entity link.

This file ships the function signature + a clean is_available() guard
so the discovery orchestrator can call it without crashing. When the
underlying API is reachable, swap the body in -- no changes required
anywhere else in the codebase.

LEGAL POSTURE: This will ONLY use the official LinkedIn API with a
valid token. We do NOT scrape LinkedIn -- their ToS prohibits it and
LinkedIn aggressively bans accounts found doing it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from salespilot.models.integrations import Integration


log = logging.getLogger(__name__)


@dataclass
class LinkedInCustomerHit:
    name: str
    source_post_urn: str       # e.g. urn:li:ugcPost:7080000000000000000
    source_post_url: str       # https://www.linkedin.com/feed/update/...
    evidence_quote: str | None
    posted_at: str | None
    confidence: int


async def is_linkedin_marketing_available(db: AsyncSession) -> tuple[bool, str]:
    """Check if we have the required LinkedIn Marketing Developer Platform
    token to actually call the API.

    Returns (available, reason). reason is a human-readable explanation
    suitable for the UI 'wacht op LinkedIn API toegang' tooltip.
    """
    row = (
        await db.execute(
            select(Integration).where(
                Integration.kind == "linkedin",
                Integration.is_enabled == True,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return False, "LinkedIn integratie niet geconfigureerd"
    cfg = row.config_json or {}
    if not cfg.get("access_token"):
        return False, "LinkedIn OAuth-flow nog niet doorlopen"
    # Marketing Developer Platform unlocks the 'r_organization_social'
    # scope. The standard 'w_member_social' scope (which we have for
    # publishing) is NOT enough for organization-level reads.
    scopes = cfg.get("granted_scopes") or ""
    if "r_organization_social" not in scopes:
        return False, (
            "Marketing Developer Platform-toegang ontbreekt (scope "
            "r_organization_social). Approval status check op "
            "https://www.linkedin.com/developers/apps -> Products"
        )
    return True, "OK"


async def crawl_msp_linkedin_official(
    *,
    db: AsyncSession,
    org_id: UUID,
    msp_name: str,
    msp_website: str | None,
    max_results: int = 100,
) -> list[LinkedInCustomerHit]:
    """Extract customer mentions from an MSP's LinkedIn organization posts.

    STUB IMPLEMENTATION: returns []. Will be activated when
    is_linkedin_marketing_available() returns True. The full implementation
    will:

      1) Look up the MSP's organization URN via the Organization Lookup
         API (?q=vanityName&vanityName=<slug-from-website>).
      2) Fetch the org's recent UGC Posts via
         /v2/ugcPosts?q=authors&authors=List(urn:li:organization:NNN).
      3) For each post, AI-classify whether it announces a new customer.
      4) Return LinkedInCustomerHit rows with evidence + post URL.
    """
    available, reason = await is_linkedin_marketing_available(db)
    if not available:
        log.info("LinkedIn official crawl skipped for %s: %s", msp_name, reason)
        return []

    # TODO: implement once Marketing Developer Platform approval lands.
    # The implementation will mirror what we already do in
    # salespilot.integrations.linkedin (OAuth flow, refresh-token
    # handling), just calling different endpoints.
    log.warning(
        "LinkedIn Marketing scope IS available but crawl not yet "
        "implemented. msp=%s -- this is a one-day build once the API "
        "is reachable.", msp_name,
    )
    return []
