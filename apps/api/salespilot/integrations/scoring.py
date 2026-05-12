"""Lead scoring.

A deterministic, transparent scoring function. We avoid an ML model on
purpose so users can reason about why a lead got the score it did, and
so the score breakdown can be displayed in the UI.

Score components (max ~120 raw, clamped to 100):
  - ICP fit (employees 20-60):          +30
  - Mid-fit (1-19 or 61-150):           +10
  - Pricing page visited (last 30d):    +25
  - Contact page visited:               +10
  - Case study page visited:            +10
  - Return visitor (2+ distinct days):  +20
  - Microsoft 365 detected:             +10
  - Google Workspace detected:          +10
  - Recent activity (<1h):              +10
  - Active visit today:                 +5
"""

from datetime import UTC, datetime, timedelta
from typing import Iterable


def _has_keyword_in_urls(urls: Iterable[str], keywords: tuple[str, ...]) -> bool:
    for u in urls:
        u_l = (u or "").lower()
        if any(k in u_l for k in keywords):
            return True
    return False


def compute_score(
    *,
    employees: int | None,
    mail_platform: str,
    pageview_urls: list[str],
    pageview_dates: list[datetime],
    last_visit_at: datetime | None,
) -> tuple[int, list[tuple[str, int]]]:
    """Return (score, breakdown). Score is clamped to 0-100.

    breakdown is a list of (label, delta) so the UI can render
    'why this score?'.
    """
    now = datetime.now(UTC)
    breakdown: list[tuple[str, int]] = []
    total = 0

    if employees is not None:
        if 20 <= employees <= 60:
            breakdown.append(("ICP fit (size 20-60)", 30))
            total += 30
        elif 1 <= employees <= 19 or 61 <= employees <= 150:
            breakdown.append(("Mid-fit company size", 10))
            total += 10
        # Out-of-band sizes contribute 0.

    if _has_keyword_in_urls(pageview_urls, ("pricing", "tarieven", "prijs")):
        breakdown.append(("Pricing page visited", 25))
        total += 25
    if _has_keyword_in_urls(pageview_urls, ("contact",)):
        breakdown.append(("Contact page visited", 10))
        total += 10
    if _has_keyword_in_urls(pageview_urls, ("case", "klantverhaal", "customer")):
        breakdown.append(("Case study page visited", 10))
        total += 10

    distinct_days = {d.date() for d in pageview_dates}
    if len(distinct_days) >= 2:
        breakdown.append(("Return visitor", 20))
        total += 20

    if mail_platform == "m365":
        breakdown.append(("Microsoft 365 detected", 10))
        total += 10
    elif mail_platform == "google":
        breakdown.append(("Google Workspace detected", 10))
        total += 10

    if last_visit_at is not None:
        age = now - last_visit_at
        if age <= timedelta(hours=1):
            breakdown.append(("Recent activity (<1h)", 10))
            total += 10
        elif age <= timedelta(days=1):
            breakdown.append(("Active today", 5))
            total += 5

    return max(0, min(100, total)), breakdown


def bucket(score: int) -> str:
    """hot / warm / cold."""
    if score >= 80:
        return "hot"
    if score >= 50:
        return "warm"
    return "cold"
