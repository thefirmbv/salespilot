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
# Totale omzet per maand + groei-projectie (€1M-doel tracking)
# ----------------------------------------------------------------------


class RevenueMonth(BaseModel):
    year: int
    month: int
    label: str
    revenue: float           # WERKELIJK gefactureerd (posted invoices) tot nu
    invoice_count: int
    # Per maand kunnen er meerdere "componenten" zijn:
    is_current_month: bool = False  # = lopende maand, telt NIET in trend-fit
    is_projection: bool = False     # = nog niet bestaande maand (in toekomst)
    pending_recurring: float = 0.0  # nog te factureren recurring deze maand
    pending_labor_estimate: float = 0.0  # handmatige open-labor schatting
    acquisition_uplift: float = 0.0  # toegevoegd op basis van nieuwe deals


class GrowthProjection(BaseModel):
    """Maandelijkse omzet + projectie naar einde van het jaar.

    BELANGRIJK: lopende maand wordt apart behandeld.
    Een halve maand telt niet als 'data' want recurring + labor moet
    nog gefactureerd worden. Voor de huidige maand tonen we:
      - werkelijk gefactureerd tot vandaag (blauw)
      - nog te factureren recurring deze maand (groene top)
      - schatting open labor uit HaloPSA (geen API-toegang -> handmatig param)

    Acquisitie-impact: gemiddeld # nieuwe deals/mnd × gem amount
    × recurring_fraction. Toegevoegd aan toekomstige maanden als
    'acquisition_uplift'.
    """
    months_history: list[RevenueMonth]  # afgeronde maanden, telt mee in regressie
    current_month: RevenueMonth | None  # lopende maand (is_current_month=true)
    months_projection: list[RevenueMonth]  # toekomstige maanden, is_projection=true

    average_per_month: float          # gem over hele history-window (excl current)
    growth_per_month: float           # lineaire trend
    year_to_date: float               # huidig kalenderjaar tot vandaag (incl current)

    # Drie projectie-varianten zodat we kunnen vergelijken
    projection_full_year_linear: float       # YTD + trend-projectie + lopende-mnd top-up
    projection_full_year_average: float      # YTD + (avg × resterende mnd)
    projection_full_year_with_acquisition: float  # linear + verwachte nieuwe deals

    target_one_million: float
    target_pct_achieved: float
    target_pct_projected: float        # gebaseerd op linear + acquisition
    target_met: bool
    target_gap_to_million: float

    # Acquisitie-context
    avg_deals_won_per_month: float
    avg_deal_amount: float
    acquisition_recurring_fraction: float  # aanname: hoeveel % van deal-amount is recurring jaarwaarde
    acquisition_monthly_uplift: float  # = avg_deals × avg_amount × fraction / 12


@router.get("/revenue-growth", response_model=GrowthProjection)
async def revenue_growth(
    auth: CurrentAuth, db: Db,
    months: int = Query(24, ge=6, le=36),
    open_labor_estimate: float = Query(
        0.0,
        description="Handmatige schatting open labor voor lopende maand "
        "(uren × tarief). HaloPSA TimeSheet/Tickets endpoints zijn 403 voor "
        "onze scope dus moet handmatig worden ingevuld.",
    ),
    acquisition_recurring_fraction: float = Query(
        0.5, ge=0.0, le=1.0,
        description="Aanname: welk percentage van won-deal amount is "
        "recurring jaarwaarde (rest = eenmalig). Default 50%.",
    ),
    include_acquisition: bool = Query(True),
) -> GrowthProjection:
    """Totale omzet per maand + EUR 1M target tracking.

    KRITISCH: lopende maand wordt apart behandeld omdat:
      - Recurring voor deze maand soms nog niet verstuurd is
      - Open labor in HaloPSA nog moet worden gefactureerd
      Anders zou de trend-regressie op een halve maand
      gefit worden -> projectie loopt structureel te laag.

    Acquisitie: gemiddeld # won-deals/mnd × gem amount × recurring-
    fractie wordt als 'uplift' bovenop toekomstige maanden gerekend.
    """
    halo = await _halopsa_client(db)
    now = datetime.now(UTC)
    date_from = (now - timedelta(days=months * 32)).strftime("%Y-%m-%d")

    # ----- Posted invoices ophalen -----
    try:
        async with halo as c:
            d = await c._request(
                "GET", "/api/Invoice",
                params={"count": 2000, "date_from": date_from, "posted_only": "true"},
            )
            # En recurring-templates voor "nog te factureren deze maand"
            d_rec = await c._request(
                "GET", "/api/RecurringInvoice",
                params={"count": 1000, "includelines": "true"},
            )
    except HaloPSAError as e:
        raise HTTPException(status_code=502, detail=str(e))

    invs = d.get("invoices", []) if isinstance(d, dict) else []
    bucket: dict[tuple[int, int], dict[str, Any]] = defaultdict(
        lambda: {"revenue": 0.0, "invoice_count": 0}
    )
    for inv in invs:
        date_str = inv.get("invoice_date") or inv.get("date") or inv.get("date_created") or ""
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        try:
            tot = float(inv.get("total") or inv.get("net_total") or 0)
        except (TypeError, ValueError):
            tot = 0.0
        key = (dt.year, dt.month)
        bucket[key]["revenue"] += tot
        bucket[key]["invoice_count"] += 1

    sorted_keys = sorted(bucket.keys())
    if not sorted_keys:
        raise HTTPException(status_code=404, detail="Geen invoice-data gevonden.")

    # Filter ruisige start-maanden (< 10% van max)
    max_rev = max(b["revenue"] for b in bucket.values())
    threshold = max_rev * 0.10
    filtered_keys = [k for k in sorted_keys if bucket[k]["revenue"] >= threshold]
    if len(filtered_keys) < 6:
        filtered_keys = sorted_keys

    # ----- Splits in history (afgeronde maanden) en current_month -----
    current_key = (now.year, now.month)
    history_keys = [k for k in filtered_keys if k != current_key]

    history: list[RevenueMonth] = []
    for y, m in history_keys:
        v = bucket[(y, m)]
        history.append(RevenueMonth(
            year=y, month=m, label=f"{y}-{m:02d}",
            revenue=round(v["revenue"], 2),
            invoice_count=int(v["invoice_count"]),
            is_current_month=False,
            is_projection=False,
        ))

    # ----- Recurring nog te factureren deze maand -----
    pending_recurring_this_month = 0.0
    rec_invs = d_rec.get("invoices", []) if isinstance(d_rec, dict) else []
    for inv in rec_invs:
        if inv.get("disabled"):
            continue
        next_str = inv.get("nextcreationperiod", "")
        try:
            start_part = next_str.split(" - ")[0]
            next_dt = datetime.strptime(start_part, "%d/%m/%Y %H:%M")
        except (ValueError, IndexError):
            continue
        if next_dt.year == now.year and next_dt.month == now.month:
            cycle_total = sum(
                float(ln.get("total_price") or 0)
                for ln in (inv.get("lines") or [])
            )
            pending_recurring_this_month += cycle_total

    # ----- Current-month object bouwen -----
    current_actual = bucket.get(current_key, {"revenue": 0.0, "invoice_count": 0})
    current_month = RevenueMonth(
        year=now.year, month=now.month, label=f"{now.year}-{now.month:02d}",
        revenue=round(current_actual["revenue"], 2),
        invoice_count=int(current_actual["invoice_count"]),
        is_current_month=True,
        is_projection=False,
        pending_recurring=round(pending_recurring_this_month, 2),
        pending_labor_estimate=round(open_labor_estimate, 2),
    )

    n = len(history)
    revenues = [h.revenue for h in history]
    avg = sum(revenues) / max(1, n)

    # ----- Lineaire regressie OP AFGERONDE MAANDEN (geen current) -----
    if n >= 2:
        xs = list(range(n))
        x_mean = sum(xs) / n
        y_mean = sum(revenues) / n
        num = sum((xs[i] - x_mean) * (revenues[i] - y_mean) for i in range(n))
        den = sum((xs[i] - x_mean) ** 2 for i in range(n)) or 1.0
        slope = num / den
        intercept = y_mean - slope * x_mean
    else:
        slope = 0.0
        intercept = revenues[0] if revenues else 0.0

    # ----- Acquisitie-uplift: gem deals/mnd × gem amount × fractie / 12 -----
    avg_deals_per_month = 0.0
    avg_deal_amount = 0.0
    acq_monthly_uplift = 0.0
    if include_acquisition:
        from salespilot.models.crm import Deal
        cutoff = now - timedelta(days=365)
        # Naive datetime voor SQL compare
        try:
            won_deals = (await db.execute(
                select(Deal).where(
                    Deal.status == "won",
                    Deal.closed_at >= cutoff,
                    Deal.closed_at.is_not(None),
                )
            )).scalars().all()
            if won_deals:
                amounts = [float(d.amount or 0) for d in won_deals]
                # Maanden verspreid?
                months_covered = len({
                    (d.closed_at.year, d.closed_at.month) for d in won_deals
                })
                if months_covered > 0:
                    avg_deals_per_month = len(won_deals) / months_covered
                    avg_deal_amount = sum(amounts) / len(amounts)
                    # Recurring jaarwaarde / 12 = maandelijkse uplift per nieuwe klant
                    acq_monthly_uplift = (
                        avg_deals_per_month * avg_deal_amount
                        * acquisition_recurring_fraction
                        / 12
                    )
        except Exception:
            pass

    # ----- Projecteer toekomstige maanden tot eind van huidig kalenderjaar -----
    projection: list[RevenueMonth] = []
    last_y, last_m = current_key
    py, pm = last_y, last_m
    step_count = 0
    while True:
        pm += 1
        if pm > 12:
            pm = 1
            py += 1
        step_count += 1
        base = max(0.0, intercept + slope * (n + step_count))
        # Acquisitie uplift accumuleert: maand 1 = 1 nieuwe-klant-set,
        # maand 2 = 2 nieuwe-klant-sets, etc (compound)
        uplift = acq_monthly_uplift * step_count
        projection.append(RevenueMonth(
            year=py, month=pm, label=f"{py}-{pm:02d}",
            revenue=round(base + uplift, 2),
            invoice_count=0,
            is_current_month=False,
            is_projection=True,
            acquisition_uplift=round(uplift, 2),
        ))
        if py == now.year and pm == 12:
            break
        if step_count >= 24:
            break

    # ----- YTD = som van afgeronde-history + current_month TOTAAL -----
    # Voor current_month tellen we werkelijk gefactureerd + nog-te-factureren mee
    current_estimated_total = (
        current_month.revenue
        + current_month.pending_recurring
        + current_month.pending_labor_estimate
    )
    ytd = sum(h.revenue for h in history if h.year == now.year) + current_estimated_total

    # ----- Drie projectie-varianten -----
    proj_curr_year_linear = sum(p.revenue - p.acquisition_uplift for p in projection if p.year == now.year)
    proj_curr_year_acquisition = sum(p.revenue for p in projection if p.year == now.year)
    months_remaining = sum(1 for p in projection if p.year == now.year)

    projection_full_year_linear = ytd + proj_curr_year_linear
    projection_full_year_average = ytd + (avg * months_remaining)
    projection_full_year_with_acquisition = ytd + proj_curr_year_acquisition

    target = 1_000_000.0
    return GrowthProjection(
        months_history=history,
        current_month=current_month,
        months_projection=projection,
        average_per_month=round(avg, 2),
        growth_per_month=round(slope, 2),
        year_to_date=round(ytd, 2),
        projection_full_year_linear=round(projection_full_year_linear, 2),
        projection_full_year_average=round(projection_full_year_average, 2),
        projection_full_year_with_acquisition=round(projection_full_year_with_acquisition, 2),
        target_one_million=target,
        target_pct_achieved=round(ytd / target * 100, 1),
        target_pct_projected=round(projection_full_year_with_acquisition / target * 100, 1),
        target_met=projection_full_year_with_acquisition >= target,
        target_gap_to_million=round(target - projection_full_year_with_acquisition, 2),
        avg_deals_won_per_month=round(avg_deals_per_month, 2),
        avg_deal_amount=round(avg_deal_amount, 2),
        acquisition_recurring_fraction=acquisition_recurring_fraction,
        acquisition_monthly_uplift=round(acq_monthly_uplift, 2),
    )

# ----------------------------------------------------------------------
# Top klanten op WERKELIJKE omzet (niet recurring projectie)
# ----------------------------------------------------------------------


class ClientRevenueRow(BaseModel):
    client_name: str
    revenue: float
    invoice_count: int


@router.get("/top-clients-actual", response_model=list[ClientRevenueRow])
async def top_clients_actual(
    auth: CurrentAuth, db: Db,
    months: int = Query(12, ge=1, le=36),
    limit: int = Query(15, ge=1, le=50),
) -> list[ClientRevenueRow]:
    """Top klanten op WERKELIJK gefactureerde omzet (posted invoices).
    Verschilt van /recurring-summary top_clients: project-werk + eenmalig
    werk wordt hier wel meegenomen, daar niet."""
    client = await _halopsa_client(db)
    now = datetime.now(UTC)
    date_from = (now - timedelta(days=months * 32)).strftime("%Y-%m-%d")
    try:
        async with client as c:
            d = await c._request(
                "GET", "/api/Invoice",
                params={"count": 2000, "date_from": date_from, "posted_only": "true"},
            )
    except HaloPSAError as e:
        raise HTTPException(status_code=502, detail=str(e))

    invs = d.get("invoices", []) if isinstance(d, dict) else []
    by_client: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"revenue": 0.0, "invoice_count": 0}
    )
    cutoff = now - timedelta(days=months * 30.5)
    for inv in invs:
        ds = inv.get("invoice_date") or inv.get("date") or ""
        try:
            dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
            # Normaliseer naar timezone-aware UTC voor compare
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            if dt < cutoff:
                continue
        except (ValueError, AttributeError):
            continue
        try:
            tot = float(inv.get("total") or inv.get("net_total") or 0)
        except (TypeError, ValueError):
            tot = 0.0
        name = inv.get("client_name") or "(onbekend)"
        by_client[name]["revenue"] += tot
        by_client[name]["invoice_count"] += 1

    rows = [
        ClientRevenueRow(
            client_name=n, revenue=round(v["revenue"], 2),
            invoice_count=int(v["invoice_count"]),
        )
        for n, v in by_client.items()
    ]
    rows.sort(key=lambda r: -r.revenue)
    return rows[:limit]


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
