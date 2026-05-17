"""Plesk state poller.

Per org: fetch /clients, /subscriptions (with domain fallback), /domains
and upsert into postgres. Detect status changes and log them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from salespilot.integrations.plesk import PleskClient
from salespilot.models.hosting import (
    PleskDomain, PleskStateEvent, PleskSubscription,
)


def _parse_iso(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _sub_status(raw: dict[str, Any]) -> str:
    """Map Plesk subscription state to our 3-bucket model."""
    if raw.get("disabled") or raw.get("status") == "disabled":
        return "disabled"
    if raw.get("suspended"):
        return "suspended"
    return "active"


async def poll_plesk_for_org(
    db: AsyncSession, *, org_id: UUID, client: PleskClient,
    server_id: UUID | None = None,
) -> dict[str, Any]:
    """Poll one Plesk server. server_id wordt op elke row gezet voor
    multi-server traceability."""
    polled_at = datetime.now(UTC)

    subs_raw = await client.list_subscriptions()
    domains_raw = await client.list_domains()

    # ---- subscriptions ----
    subs_by_pid = {
        s.plesk_id: s
        for s in (await db.execute(select(PleskSubscription))).scalars()
    }
    subs_new = 0
    state_events = 0

    for raw in subs_raw:
        pid = str(raw.get("id") or raw.get("subscription_id") or raw.get("guid") or "")
        if not pid:
            continue
        existing = subs_by_pid.get(pid)
        new_status = _sub_status(raw)
        previous_status = existing.status if existing else None

        if existing is None:
            existing = PleskSubscription(
                id=uuid4(), org_id=org_id, plesk_id=pid,
                server_id=server_id,
            )
            db.add(existing)
            subs_new += 1
            subs_by_pid[pid] = existing
        elif server_id is not None:
            existing.server_id = server_id

        if previous_status and previous_status != new_status:
            db.add(PleskStateEvent(
                id=uuid4(), org_id=org_id,
                subscription_id=existing.id,
                previous_status=previous_status,
                new_status=new_status,
                occurred_at=polled_at,
                snapshot={
                    "name": existing.name,
                    "main_domain": existing.main_domain,
                },
            ))
            state_events += 1
            existing.last_status_change = polled_at

        existing.name = (
            raw.get("name") or raw.get("subscription_name")
            or raw.get("domain") or existing.name or ""
        )[:255]
        existing.main_domain = (raw.get("domain") or raw.get("name") or "")[:255] or None
        existing.owner_login = raw.get("owner_login") or raw.get("login")
        existing.owner_email = raw.get("email") or raw.get("contact_email")
        existing.plan_name = raw.get("plan") or raw.get("plan_name") or raw.get("hosting_plan")
        existing.plan_id = raw.get("plan_id")
        existing.status = new_status
        existing.is_enabled = new_status == "active"
        # Resource usage (best-effort, fields differ per Plesk version)
        existing.disk_used_mb = int(raw.get("disk_usage") or raw.get("disk_used") or 0) // (1024*1024 or 1) if raw.get("disk_usage") else int(raw.get("disk_used_mb") or 0)
        existing.disk_limit_mb = raw.get("disk_limit_mb")
        existing.traffic_used_mb = int(raw.get("traffic_used_mb") or 0)
        existing.mailboxes_count = int(raw.get("mailboxes_count") or raw.get("mailbox_count") or 0)
        existing.databases_count = int(raw.get("databases_count") or raw.get("database_count") or 0)
        existing.created_in_plesk = _parse_iso(raw.get("creation_date") or raw.get("created"))
        existing.last_polled = polled_at
        existing.raw = raw

    await db.flush()

    # ---- domains ----
    domains_by_pid = {
        d.plesk_id: d
        for d in (await db.execute(select(PleskDomain))).scalars()
    }
    domains_new = 0
    for raw in domains_raw:
        pid = str(raw.get("id") or raw.get("guid") or raw.get("name", ""))
        if not pid:
            continue
        existing = domains_by_pid.get(pid)
        if existing is None:
            existing = PleskDomain(
                id=uuid4(), org_id=org_id, plesk_id=pid,
                name=(raw.get("name") or "")[:255],
                server_id=server_id,
            )
            db.add(existing)
            domains_new += 1
            domains_by_pid[pid] = existing
        elif server_id is not None:
            existing.server_id = server_id
        # Match domain -> subscription
        sub_pid = str(raw.get("subscription_id") or raw.get("parent_id") or "")
        if sub_pid and sub_pid in subs_by_pid:
            existing.subscription_id = subs_by_pid[sub_pid].id
        existing.name = (raw.get("name") or existing.name)[:255]
        existing.type = (raw.get("type") or raw.get("hosting_type") or "")[:32] or None
        existing.status = "active" if raw.get("status", "active") == "active" else "disabled"
        existing.ssl_enabled = bool(raw.get("ssl_enabled") or raw.get("ssl"))
        existing.last_polled = polled_at
        existing.raw = raw

    await db.flush()

    return {
        "subscriptions_seen": len(subs_raw),
        "subscriptions_new": subs_new,
        "domains_seen": len(domains_raw),
        "domains_new": domains_new,
        "state_events": state_events,
        "polled_at": polled_at.isoformat(),
    }
