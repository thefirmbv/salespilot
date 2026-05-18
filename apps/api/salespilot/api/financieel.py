"""Financieel dashboard endpoints.

Twee feeds van HaloPSA:
  1. Recurring invoices  -- projectie 12/24/36 mnd
  2. Posted invoices    -- 8041 (= accountsid 153 'Werkuren | Ad-hoc') chart

Beide live read-only uit HaloPSA, geen caching (50 + 100 invoices is
< 5s). Bij latency-probleem zetten we het achter een server-side cache.

Helpdesk-accountcode: 153 (= "Werkuren | Ad-hoc" in HaloPSA Item-master).
Dat is de productie-koppeling naar boekingscode 8041 in jullie
boekhouding. Daadwerkelijke 8041-string staat niet op de Item; we
gebruiken de accountsid als interne match-key.

HaloPSA recurring 'period' enum (uit Style Notice + EVConsult test):
  1 = weekly
  2 = monthly
  3 = yearly
  4 = quarterly
  5 = half-yearly
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from salespilot.deps import CurrentAuth, Db
from salespilot.models.integrations import Integration
from salespilot.integrations.halopsa import (
    HaloPSAClient, HaloPSACredentials, HaloPSAError,
)


router = APIRouter(prefix="/financieel", tags=["financieel"])


# Het accountsid in HaloPSA dat correspondeert met boekingscode 8041
# (= "Werkuren | Ad-hoc"). Hardcoded voor IT-Gemak; later configurable.
HELPDESK_ACCOUNTSID = "153"

# Boekingscode 8044 Modern Work | Recurring -- nominal_code 251
# ("Modern Workspace | Jaarfacturatie"). Verkopen wij actief, dus
# eigen growth-chart.
MODERN_WORK_ACCOUNTSID = "251"

# HaloPSA recurring period enum (uit productie-observatie).
# Mappen naar jaren per cycle i.p.v. cycles per jaar -- voorkomt
# silent mis-telling bij onbekende waarden zoals period=7 (3-jaarlijks)
# die in mijn vorige versie als maandelijks werden gerekend (= 36x te hoog).
PERIOD_YEARS_PER_CYCLE: dict[int, float] = {
    1: 1 / 52,    # wekelijks
    2: 1 / 12,    # maandelijks
    3: 1.0,       # jaarlijks
    4: 1 / 4,     # kwartaal
    5: 1 / 2,     # halfjaarlijks
    7: 3.0,       # elk 3 jaar (Fiom domein-bundels)
    8: 4.0,       # elk 4 jaar (vermoedelijk)
    9: 5.0,       # elk 5 jaar (vermoedelijk)
}

PERIOD_LABELS: dict[int, str] = {
    1: "wekelijks", 2: "maandelijks", 3: "jaarlijks",
    4: "kwartaal", 5: "halfjaarlijks",
    7: "3-jaarlijks", 8: "4-jaarlijks", 9: "5-jaarlijks",
}


async def _halopsa_client(db) -> HaloPSAClient:
    row = (await db.execute(
        select(Integration).where(Integration.kind == "halopsa")
    )).scalar_one_or_none()
    if row is None or not row.is_enabled:
        raise HTTPException(status_code=400, detail="HaloPSA niet ingesteld.")
    cfg = row.config_json or {}
    creds = HaloPSACredentials(
        base_url=cfg.get("base_url", ""), client_id=cfg.get("client_id", ""),
        client_secret=cfg.get("client_secret", ""), tenant_id=cfg.get("tenant_id"),
        scopes=cfg.get("scopes") or "all",
    )
    return HaloPSAClient(creds)


# ----------------------------------------------------------------------
# Recurring projection
# ----------------------------------------------------------------------


class RecurringSummary(BaseModel):
    invoice_count: int
    line_count: int
    annual_revenue: float        # 12-mnd projectie
    revenue_24m: float           # 24-mnd
    revenue_36m: float           # 36-mnd
    by_period: dict[str, float]  # per period-type de jaarlijkse bijdrage
    top_clients: list[dict[str, Any]]  # top-10 klanten op jaarbasis


@router.get("/recurring-summary", response_model=RecurringSummary)
async def recurring_summary(auth: CurrentAuth, db: Db) -> RecurringSummary:
    """Projecteer alle huidige recurring-invoices over 12/24/36 mnd.

    Per line: total_price (= bedrag per factuur-cycle) × cycles-per-jaar.
    Som over alle lines + alle invoices = jaaromzet uit recurring.
    """
    client = await _halopsa_client(db)
    try:
        async with client as c:
            d = await c._request(
                "GET", "/api/RecurringInvoice",
                params={"count": 1000, "includelines": "true"},
            )
    except HaloPSAError as e:
        raise HTTPException(status_code=502, detail=str(e))

    invs = d.get("invoices", []) if isinstance(d, dict) else []
    annual = 0.0
    by_period: dict[int, float] = defaultdict(float)
    by_client: dict[str, float] = defaultdict(float)
    line_count = 0

    skipped_periods: dict[int, int] = defaultdict(int)
    for inv in invs:
        if inv.get("disabled"):
            continue
        period = int(inv.get("period") or 2)
        years_per_cycle = PERIOD_YEARS_PER_CYCLE.get(period)
        if years_per_cycle is None:
            # Onbekende period: SKIP en log (beter dan stille mis-telling)
            skipped_periods[period] += 1
            continue
        client_name = inv.get("client_name") or "(onbekend)"
        for ln in inv.get("lines") or []:
            line_count += 1
            try:
                price = float(ln.get("total_price") or ln.get("net_amount") or 0)
            except (TypeError, ValueError):
                price = 0.0
            # price = bedrag per cycle. Jaarbijdrage = price / years_per_cycle
            yearly = price / years_per_cycle if years_per_cycle > 0 else 0
            annual += yearly
            by_period[period] += yearly
            by_client[client_name] += yearly

    by_period_str = {PERIOD_LABELS.get(p, f"period-{p}"): round(v, 2) for p, v in by_period.items()}

    top_clients = [
        {"client_name": n, "annual_revenue": round(v, 2)}
        for n, v in sorted(by_client.items(), key=lambda x: -x[1])[:10]
    ]

    return RecurringSummary(
        invoice_count=len([i for i in invs if not i.get("disabled")]),
        line_count=line_count,
        annual_revenue=round(annual, 2),
        revenue_24m=round(annual * 2, 2),
        revenue_36m=round(annual * 3, 2),
        by_period=by_period_str,
        top_clients=top_clients,
    )


# ----------------------------------------------------------------------
# Helpdesk (8041) per maand
# ----------------------------------------------------------------------


class HelpdeskMonthRow(BaseModel):
    year: int
    month: int
    label: str        # "2025-08"
    revenue: float
    line_count: int


class HelpdeskTrend(BaseModel):
    accountsid: str
    months: list[HelpdeskMonthRow]
    average: float          # gemiddeld per maand over de afgelopen 12
    growth_per_month: float # lineaire trend (€/maand richting omhoog/omlaag)
    projection: list[HelpdeskMonthRow]  # 12 maanden vooruit op huidige trend
    total_last_12: float
    total_projected_next_12: float


@router.get("/account-trend", response_model=HelpdeskTrend)
async def account_trend(
    auth: CurrentAuth, db: Db,
    months: int = Query(12, ge=1, le=36),
    accountsid: str = Query(...),
) -> HelpdeskTrend:
    """Generieke per-account-code trend. Wrapper rond helpdesk_trend
    met andere accountsid. Voor 8041 (helpdesk) en 8044 (Modern Work)."""
    return await helpdesk_trend(auth=auth, db=db, months=months, accountsid=accountsid)


@router.get("/helpdesk-trend", response_model=HelpdeskTrend)
async def helpdesk_trend(
    auth: CurrentAuth, db: Db,
    months: int = Query(12, ge=1, le=36),
    accountsid: str = Query(HELPDESK_ACCOUNTSID),
) -> HelpdeskTrend:
    """Helpdesk (boekingscode 8041 ~ HaloPSA accountsid 153) per maand
    over de afgelopen N maanden. Plus lineaire trend-projectie.

    De accountsid is configurable mocht jullie boekhouding ooit een
    andere code aan helpdesk koppelen.
    """
    client = await _halopsa_client(db)
    now = datetime.now(UTC)
    # We pakken ietsje meer dan `months` (1 maand extra buffer voor partial)
    date_from = (now - timedelta(days=months * 32)).strftime("%Y-%m-%d")

    try:
        async with client as c:
            d = await c._request(
                "GET", "/api/Invoice",
                params={
                    "count": 1500, "includedetails": "true",
                    "includelines": "true",
                    "date_from": date_from, "posted_only": "true",
                },
            )
    except HaloPSAError as e:
        raise HTTPException(status_code=502, detail=str(e))

    invs = d.get("invoices", []) if isinstance(d, dict) else []

    # Bucket per (year, month)
    bucket: dict[tuple[int, int], dict[str, Any]] = defaultdict(
        lambda: {"revenue": 0.0, "line_count": 0}
    )
    for inv in invs:
        date_str = inv.get("invoice_date") or inv.get("date") or inv.get("date_created") or ""
        try:
            inv_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        for ln in inv.get("lines") or []:
            ac = str(ln.get("nominal_code") or ln.get("accountsid") or "")
            if ac != accountsid:
                continue
            try:
                price = float(ln.get("total_price") or ln.get("net_amount") or 0)
            except (TypeError, ValueError):
                price = 0.0
            key = (inv_date.year, inv_date.month)
            bucket[key]["revenue"] += price
            bucket[key]["line_count"] += 1

    # Vul de N maanden af, oudste eerst
    rows: list[HelpdeskMonthRow] = []
    for i in range(months, 0, -1):
        # i maanden geleden vanaf 'nu'
        y, m = now.year, now.month - (i - 1)
        while m <= 0:
            m += 12
            y -= 1
        v = bucket.get((y, m), {"revenue": 0.0, "line_count": 0})
        rows.append(HelpdeskMonthRow(
            year=y, month=m, label=f"{y}-{m:02d}",
            revenue=round(v["revenue"], 2),
            line_count=int(v["line_count"]),
        ))

    # Lineaire regressie y = a*x + b, x=maand-index (0..N-1)
    n = len(rows)
    if n >= 2:
        xs = list(range(n))
        ys = [r.revenue for r in rows]
        x_mean = sum(xs) / n
        y_mean = sum(ys) / n
        num = sum((xs[i] - x_mean) * (ys[i] - y_mean) for i in range(n))
        den = sum((xs[i] - x_mean) ** 2 for i in range(n)) or 1.0
        slope = num / den
        intercept = y_mean - slope * x_mean
    else:
        slope = 0.0
        intercept = rows[0].revenue if rows else 0.0

    # Projecteer 12 maanden vooruit
    projection: list[HelpdeskMonthRow] = []
    last_y, last_m = (rows[-1].year, rows[-1].month) if rows else (now.year, now.month)
    for i in range(1, 13):
        py, pm = last_y, last_m + i
        while pm > 12:
            pm -= 12
            py += 1
        predicted = intercept + slope * (n + i - 1)
        projection.append(HelpdeskMonthRow(
            year=py, month=pm, label=f"{py}-{pm:02d}",
            revenue=round(max(0.0, predicted), 2),
            line_count=0,  # niet bekend in projectie
        ))

    avg = sum(r.revenue for r in rows) / max(1, len(rows))
    total = sum(r.revenue for r in rows)
    proj_total = sum(p.revenue for p in projection)

    return HelpdeskTrend(
        accountsid=accountsid,
        months=rows,
        average=round(avg, 2),
        growth_per_month=round(slope, 2),
        projection=projection,
        total_last_12=round(total, 2),
        total_projected_next_12=round(proj_total, 2),
    )


# ----------------------------------------------------------------------
# Account-code catalog (zodat UI selecteren kan)
# ----------------------------------------------------------------------


class AccountCodeRow(BaseModel):
    accountsid: str
    sample_item_name: str
    line_count: int
    revenue_last_12m: float


@router.get("/account-codes", response_model=list[AccountCodeRow])
async def list_account_codes(
    auth: CurrentAuth, db: Db,
    months: int = Query(12, ge=1, le=36),
) -> list[AccountCodeRow]:
    """Welke account-codes komen voor in de afgelopen N maanden, met
    omzet + sample item-naam. Voor de "ander code kiezen" dropdown."""
    client = await _halopsa_client(db)
    now = datetime.now(UTC)
    date_from = (now - timedelta(days=months * 32)).strftime("%Y-%m-%d")
    try:
        async with client as c:
            d = await c._request(
                "GET", "/api/Invoice",
                params={"count": 1500, "includedetails": "true",
                        "includelines": "true",
                        "date_from": date_from, "posted_only": "true"},
            )
    except HaloPSAError as e:
        raise HTTPException(status_code=502, detail=str(e))
    invs = d.get("invoices", []) if isinstance(d, dict) else []

    by_acct: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"line_count": 0, "revenue": 0.0, "sample": ""}
    )
    for inv in invs:
        for ln in inv.get("lines") or []:
            ac = str(ln.get("nominal_code") or ln.get("accountsid") or "")
            if not ac:
                continue
            try:
                price = float(ln.get("total_price") or ln.get("net_amount") or 0)
            except (TypeError, ValueError):
                price = 0.0
            d = by_acct[ac]
            d["line_count"] += 1
            d["revenue"] += price
            if not d["sample"]:
                d["sample"] = (ln.get("item_name") or ln.get("description") or "")[:80]
    rows = [
        AccountCodeRow(
            accountsid=ac, sample_item_name=v["sample"],
            line_count=v["line_count"], revenue_last_12m=round(v["revenue"], 2),
        )
        for ac, v in by_acct.items()
    ]
    rows.sort(key=lambda r: -r.revenue_last_12m)
    return rows
