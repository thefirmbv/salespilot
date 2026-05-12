"""Autopilot engine — template rendering, send-window math, scheduler.

The scheduler runs on a cron-driven endpoint (/internal/autopilot/tick).
Each tick:
  1. Auto-enrols prospects matching live sequences' score buckets.
  2. Picks due enrollments and runs their next step.
  3. Updates next_action_at + status; stops on reply / suppression.

This is intentionally simple. No celery, no rq. The tick endpoint is
guarded by a static internal token in env (so a cron job can hit it).
"""

import re
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo


VAR_RE = re.compile(r"\{\{\s*([a-z][a-z0-9_.]*)\s*\}\}", re.IGNORECASE)


def _platform_label(p: str) -> str:
    return {
        "m365": "Microsoft 365",
        "google": "Google Workspace",
        "other": "een eigen mailomgeving",
        "unknown": "een onbekende mailomgeving",
    }.get(p, p)


def render_template(template: str, *, company: Any, contact: Any | None = None) -> str:
    """Replace `{{var.path}}` placeholders.

    Supported namespaces:
      company.name, company.domain, company.industry, company.employees,
      company.city, company.country, company.mail_platform,
      company.mail_platform_label
      contact.first_name, contact.last_name, contact.email
    Unknown variables are replaced with an empty string (silent fail —
    better than 500-ing on a draft template).
    """
    if not template:
        return template

    def get(path: str) -> str:
        parts = path.split(".")
        if not parts:
            return ""
        head, *rest = parts
        obj = None
        if head == "company":
            obj = company
        elif head == "contact":
            obj = contact
        if obj is None:
            return ""
        for r in rest:
            if r == "mail_platform_label" and head == "company":
                val = getattr(obj, "mail_platform", None)
                if hasattr(val, "value"):
                    val = val.value
                return _platform_label(val or "unknown")
            if r == "first_name" and head == "contact":
                fn = getattr(obj, "first_name", None)
                return fn or ""
            val = getattr(obj, r, None)
            if val is None:
                return ""
            return str(val)
        return ""

    return VAR_RE.sub(lambda m: get(m.group(1)), template)


def next_send_slot(window: dict, *, after: datetime) -> datetime:
    """Compute the next datetime inside the configured send window.

    window['days'] is ISO weekday list (1=Mon).
    window['hours'] is a list of [start, end] pairs in window['tz'] local time.
    """
    tz = ZoneInfo(window.get("tz", "Europe/Amsterdam"))
    days = window.get("days") or [1, 2, 3, 4, 5]
    hour_pairs = window.get("hours") or [[9, 17]]
    # Normalise.
    hour_pairs = [tuple(p) for p in hour_pairs if isinstance(p, (list, tuple)) and len(p) == 2]
    if not hour_pairs:
        hour_pairs = [(9, 17)]

    local = after.astimezone(tz)
    # Walk forward day by day for up to 14 days — beyond that the window
    # config is broken.
    for delta in range(0, 14):
        candidate_day = local + timedelta(days=delta)
        if candidate_day.isoweekday() not in days:
            continue
        for start_h, end_h in hour_pairs:
            slot_start = candidate_day.replace(hour=start_h, minute=0, second=0, microsecond=0)
            slot_end = candidate_day.replace(hour=end_h, minute=0, second=0, microsecond=0)
            if delta == 0:
                if local >= slot_end:
                    continue
                if local < slot_start:
                    return slot_start.astimezone(UTC)
                # Inside an active slot already — send now.
                return local.astimezone(UTC)
            else:
                return slot_start.astimezone(UTC)
    # Fallback — 24h from now.
    return after + timedelta(hours=24)


def compute_next_action_at(
    *, last_action_at: datetime | None, wait_days: int, window: dict, cooldown_hours: int
) -> datetime:
    """Earliest send time honouring cooldown + wait_days + window."""
    base = last_action_at or datetime.now(UTC)
    earliest = base + timedelta(days=max(0, wait_days))
    cooldown_after = base + timedelta(hours=max(0, cooldown_hours))
    target = max(earliest, cooldown_after, datetime.now(UTC))
    return next_send_slot(window, after=target)


def bucket_for_score(score: int) -> str:
    if score >= 80:
        return "hot"
    if score >= 50:
        return "warm"
    return "cold"
