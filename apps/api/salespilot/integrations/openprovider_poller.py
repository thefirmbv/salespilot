"""Openprovider domain poller."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from salespilot.integrations.openprovider import OpenproviderClient
from salespilot.models.hosting import OpenproviderDomain


def _parse_iso(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def poll_openprovider_for_org(
    db: AsyncSession, *, org_id: UUID, client: OpenproviderClient,
) -> dict[str, Any]:
    polled_at = datetime.now(UTC)
    raw_domains = await client.list_all_domains()

    by_op_id = {
        d.op_id: d
        for d in (await db.execute(select(OpenproviderDomain))).scalars()
    }
    new_count = 0

    for raw in raw_domains:
        op_id = str(raw.get("id") or "")
        if not op_id:
            continue
        domain_obj = raw.get("domain") or {}
        if isinstance(domain_obj, dict):
            name = domain_obj.get("name", "")
            ext = domain_obj.get("extension", "")
            full = f"{name}.{ext}" if name and ext else (name or ext)
        else:
            full = str(domain_obj)
            ext = full.split(".", 1)[1] if "." in full else None

        existing = by_op_id.get(op_id)
        if existing is None:
            existing = OpenproviderDomain(
                id=uuid4(), org_id=org_id, op_id=op_id, name=full[:255],
            )
            db.add(existing)
            new_count += 1
            by_op_id[op_id] = existing

        existing.name = full[:255]
        existing.extension = (ext or "")[:16] or None
        existing.status = (raw.get("status") or "active")[:32]
        existing.auto_renew = bool(raw.get("autorenew") in (1, "1", True, "on"))
        existing.registered_at = _parse_iso(raw.get("creation_date"))
        existing.expires_at = _parse_iso(raw.get("expiration_date"))
        existing.nameservers = raw.get("name_servers") or []
        existing.owner_handle = raw.get("owner_handle")
        existing.is_locked = bool(raw.get("is_locked"))
        existing.last_polled = polled_at
        existing.raw = raw

    await db.flush()
    return {
        "domains_seen": len(raw_domains),
        "domains_new": new_count,
        "polled_at": polled_at.isoformat(),
    }
