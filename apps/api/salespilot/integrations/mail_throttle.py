"""Sender-reputation throttle for outbound email.

We're intentionally conservative because mail.it-gemak.nl is a brand-new
subdomain; aggressive sending would tank deliverability before warm-up
is complete. Defaults are:

  * max_per_day      = 30   (warm-up; bump after first 2 weeks clean)
  * max_per_hour     = 6
  * min_seconds_gap  = 90   (no two mails within 90s)

These can be overridden per integration in config_json under
'limits': { 'max_per_day': N, 'max_per_hour': N, 'min_seconds_gap': N }.

The throttle is enforced by counting actual sent rows in the `messages`
table within the relevant window. Failed sends don't count -- we want
to be able to retry without the bounce eating our budget.

Returns (allowed, retry_after_seconds, reason). When not allowed, the
caller should reschedule next_action_at to now + retry_after_seconds.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from salespilot.models.autopilot import Message
from salespilot.models.integrations import Integration


DEFAULT_MAX_PER_DAY = 30
DEFAULT_MAX_PER_HOUR = 6
DEFAULT_MIN_SECONDS_GAP = 90


def _limits_from_integration(integ: Integration) -> tuple[int, int, int]:
    cfg = integ.config_json or {}
    limits = (cfg.get("limits") if isinstance(cfg.get("limits"), dict) else None) or {}
    return (
        int(limits.get("max_per_day") or DEFAULT_MAX_PER_DAY),
        int(limits.get("max_per_hour") or DEFAULT_MAX_PER_HOUR),
        int(limits.get("min_seconds_gap") or DEFAULT_MIN_SECONDS_GAP),
    )


async def check_send_quota(
    db: AsyncSession,
    *,
    org_id: UUID,
    integ: Integration,
) -> tuple[bool, int, str]:
    """Return (allowed, retry_after_seconds, reason).

    'reason' is human-readable for logging; the engine surfaces it via
    the message row's `error` field when blocked.
    """
    max_day, max_hour, min_gap = _limits_from_integration(integ)
    now = datetime.now(UTC)

    # Last successful send -- governs min_seconds_gap
    last_sent = (
        await db.execute(
            select(func.max(Message.sent_at))
            .where(Message.channel == "email")
            .where(Message.status == "sent")
        )
    ).scalar()

    if last_sent is not None:
        gap = (now - last_sent).total_seconds()
        if gap < min_gap:
            wait = int(min_gap - gap) + 1
            return False, wait, f"min_seconds_gap ({min_gap}s); wacht {wait}s"

    # Last-hour count
    hour_ago = now - timedelta(hours=1)
    hour_count = (
        await db.execute(
            select(func.count(Message.id))
            .where(Message.channel == "email")
            .where(Message.status == "sent")
            .where(Message.sent_at >= hour_ago)
        )
    ).scalar() or 0
    if hour_count >= max_hour:
        # Push to the start of the next hour
        next_hour = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
        wait = max(60, int((next_hour - now).total_seconds()))
        return False, wait, f"max_per_hour={max_hour} bereikt ({hour_count})"

    # Last-24h count (sliding window, not calendar day)
    day_ago = now - timedelta(hours=24)
    day_count = (
        await db.execute(
            select(func.count(Message.id))
            .where(Message.channel == "email")
            .where(Message.status == "sent")
            .where(Message.sent_at >= day_ago)
        )
    ).scalar() or 0
    if day_count >= max_day:
        # Wait until the oldest one in window is more than 24h old
        oldest_in_window = (
            await db.execute(
                select(func.min(Message.sent_at))
                .where(Message.channel == "email")
                .where(Message.status == "sent")
                .where(Message.sent_at >= day_ago)
            )
        ).scalar()
        if oldest_in_window is not None:
            wait = int((oldest_in_window + timedelta(hours=24) - now).total_seconds()) + 60
            wait = max(60, wait)
        else:
            wait = 3600
        return False, wait, f"max_per_day={max_day} bereikt (24u glijdend, {day_count})"

    return True, 0, "ok"


def quota_summary_dict(integ: Integration) -> dict[str, Any]:
    max_day, max_hour, min_gap = _limits_from_integration(integ)
    return {
        "max_per_day": max_day,
        "max_per_hour": max_hour,
        "min_seconds_gap": min_gap,
    }
