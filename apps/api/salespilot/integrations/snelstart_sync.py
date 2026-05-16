"""SnelStart sync + business logic.

Two flows live here:

1. ``sepa_bulk_fix_for_org`` -- finds verkoopfacturen where
   ``isIncasso == false`` for relations that DO have an
   incassomachtiging (SEPA mandate). It can run in dry-run (preview) or
   commit mode. The HaloPSA -> SnelStart factuur sync does not always
   pass the SEPA flag; this fixes that drift with one click.

2. ``aggregate_monthly_by_group`` -- pulls the last N months of sales
   invoices, joins each to its relatie -> groep, and returns a matrix
   {month -> {groep -> total}}. Powers the Financieel > Dashboard view.

Both functions are pure-ish: they take a client + parameters and return
plain dicts. They don't touch the DB directly. The API layer decides
what to persist.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from .snelstart import SnelStartClient, SnelStartError


# ---------------------------------------------------------------------
# SEPA bulk fix
# ---------------------------------------------------------------------


def _factuur_sepa_flag(f: dict[str, Any]) -> bool | None:
    """SnelStart's payload uses 'isIncasso' on the factuur. Some legacy
    rows carry it as 'incasso'. Returns None if neither field exists."""
    for key in ("isIncasso", "incasso", "IsIncasso"):
        if key in f:
            return bool(f[key])
    return None


def _factuur_relatie_id(f: dict[str, Any]) -> str | None:
    """The relatie reference can be either an embedded object or a
    flat id string depending on $expand. Cover both shapes."""
    rel = f.get("relatie")
    if isinstance(rel, dict):
        return rel.get("id")
    if isinstance(rel, str):
        return rel
    return f.get("relatieId") or f.get("RelatieId")


def _factuur_amount(f: dict[str, Any]) -> Decimal:
    """Read totaalbedrag-incl-btw, falling back across naming variants."""
    for key in ("totaalBedragInclBtw", "totaalbedragInclBtw", "totaal", "bedrag"):
        v = f.get(key)
        if v is None:
            continue
        try:
            return Decimal(str(v))
        except (InvalidOperation, ValueError):
            continue
    return Decimal("0")


async def sepa_bulk_fix_for_org(
    client: SnelStartClient,
    *,
    dry_run: bool = True,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    page_size: int = 200,
    max_pages: int = 20,
) -> dict[str, Any]:
    """Find sales invoices missing the SEPA flag while the relation HAS
    an active SEPA mandate. Optionally PUT the fix.

    Returns
    -------
    dict with:
      ``scanned``      total invoices scanned
      ``missing_flag`` count where isIncasso=false
      ``fixable``      count where the relation has a mandate (=fixable)
      ``fixed``        count actually PUT (0 if dry_run=True)
      ``rows``         per-row preview: [{factuur_id, factuurnummer, relatie_id, relatie_naam, bedrag, action}]
      ``errors``       list of {factuur_id, error} for rows that failed PUT
    """
    # 1) Fetch all SEPA mandates and index by relatie_id. An 'active'
    #    mandate is anything that isn't explicitly intrekDatum < today.
    mandates = await client.list_incassomachtigingen()
    relaties_with_mandate: set[str] = set()
    today = datetime.now(UTC).date()
    for m in mandates:
        rel_id = (
            (m.get("relatie") or {}).get("id")
            if isinstance(m.get("relatie"), dict)
            else m.get("relatieId") or m.get("RelatieId")
        )
        if not rel_id:
            continue
        eind = m.get("eindDatum") or m.get("vervalDatum") or m.get("intrekDatum")
        if eind:
            try:
                eind_date = datetime.fromisoformat(eind.replace("Z", "+00:00")).date()
                if eind_date < today:
                    continue  # mandate expired
            except (ValueError, TypeError):
                pass
        relaties_with_mandate.add(str(rel_id))

    # 2) Page through invoices in the time window
    scanned = 0
    missing_flag = 0
    fixable_rows: list[dict[str, Any]] = []

    for page in range(max_pages):
        page_invoices = await client.list_verkoopfacturen(
            from_date=from_date,
            to_date=to_date,
            top=page_size,
            skip=page * page_size,
        )
        if not page_invoices:
            break
        for f in page_invoices:
            scanned += 1
            flag = _factuur_sepa_flag(f)
            if flag is True:
                continue  # already incasso
            if flag is False or flag is None:
                missing_flag += 1
                rel_id = _factuur_relatie_id(f)
                if rel_id and str(rel_id) in relaties_with_mandate:
                    rel_obj = f.get("relatie") if isinstance(f.get("relatie"), dict) else {}
                    fixable_rows.append({
                        "factuur_id": f.get("id"),
                        "factuurnummer": f.get("factuurnummer") or f.get("nummer"),
                        "factuurdatum": f.get("factuurdatum") or f.get("Factuurdatum"),
                        "relatie_id": rel_id,
                        "relatie_naam": rel_obj.get("naam") or rel_obj.get("name") or "",
                        "bedrag": float(_factuur_amount(f)),
                        "raw": f,
                    })
        if len(page_invoices) < page_size:
            break  # last page

    fixed = 0
    errors: list[dict[str, Any]] = []
    rows_out: list[dict[str, Any]] = []

    for r in fixable_rows:
        action = "would_fix" if dry_run else "fixing"
        if not dry_run:
            try:
                # Fetch full row (PUT in SnelStart often requires full body)
                full = r["raw"]
                # mutate the SEPA flag
                full["isIncasso"] = True
                await client.update_verkoopfactuur(r["factuur_id"], full)
                fixed += 1
                action = "fixed"
            except SnelStartError as e:
                errors.append({
                    "factuur_id": r["factuur_id"],
                    "factuurnummer": r["factuurnummer"],
                    "error": str(e)[:200],
                })
                action = "error"
        # Strip raw from response (UI doesn't need it, payload is big)
        rows_out.append({
            "factuur_id": r["factuur_id"],
            "factuurnummer": r["factuurnummer"],
            "factuurdatum": r["factuurdatum"],
            "relatie_id": r["relatie_id"],
            "relatie_naam": r["relatie_naam"],
            "bedrag": r["bedrag"],
            "action": action,
        })

    return {
        "ok": True,
        "dry_run": dry_run,
        "scanned": scanned,
        "missing_flag": missing_flag,
        "fixable": len(fixable_rows),
        "fixed": fixed,
        "rows": rows_out,
        "errors": errors,
    }


# ---------------------------------------------------------------------
# Monthly aggregation per group (Financieel > Dashboard)
# ---------------------------------------------------------------------


def _factuur_groep_id(f: dict[str, Any], rel_index: dict[str, dict[str, Any]]) -> str | None:
    """Resolve the factuur's group via its relatie. Relatie objects in
    SnelStart carry a 'groep' object with id+naam."""
    rel_id = _factuur_relatie_id(f)
    if not rel_id:
        return None
    rel = rel_index.get(str(rel_id))
    if not rel:
        return None
    groep = rel.get("groep")
    if isinstance(groep, dict):
        return groep.get("id")
    return rel.get("groepId") or rel.get("GroepId")


def _month_key(iso_date: str | None) -> str | None:
    """Turn ISO datetime/date into 'YYYY-MM'."""
    if not iso_date:
        return None
    try:
        d = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        return f"{d.year:04d}-{d.month:02d}"
    except (ValueError, TypeError):
        return None


async def aggregate_monthly_by_group(
    client: SnelStartClient,
    *,
    months: int = 4,
    page_size: int = 200,
    max_pages: int = 50,
) -> dict[str, Any]:
    """Return per-month, per-group revenue for the last ``months`` months.

    Returns
    -------
    {
      "months": ["2026-02","2026-03","2026-04","2026-05"],
      "groups": [
        {"id":"<uuid>", "naam":"Standaard"},
        {"id":"<uuid>", "naam":"Premium"},
        ...
      ],
      "matrix": {
        "<group_id>": {"2026-02": 12345.67, "2026-03": ..., ...},
        ...
      },
      "totals_per_month": {"2026-02": 99999.99, ...},
      "totals_per_group": {"<group_id>": 123456.78, ...},
      "grand_total": 999999.99,
      "invoice_count": 234,
    }
    """
    now = datetime.now(UTC)
    # Calculate cutoff: first day of N-months-ago (e.g. months=4 from
    # May-15 -> Feb 1)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for _ in range(months - 1):
        # Step back one calendar month
        if start.month == 1:
            start = start.replace(year=start.year - 1, month=12)
        else:
            start = start.replace(month=start.month - 1)

    # Build month label list (oldest -> newest)
    month_labels: list[str] = []
    cur = start
    while cur <= now:
        month_labels.append(f"{cur.year:04d}-{cur.month:02d}")
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)

    # Pre-fetch ALL relaties (cached for the lookup), AND all groups
    groepen = await client.list_groepen()
    groep_index: dict[str, dict[str, Any]] = {
        str(g.get("id")): g for g in groepen if g.get("id")
    }

    relaties_index: dict[str, dict[str, Any]] = {}
    for page in range(max_pages):
        chunk = await client.list_relaties(top=page_size, skip=page * page_size)
        if not chunk:
            break
        for r in chunk:
            rid = r.get("id")
            if rid:
                relaties_index[str(rid)] = r
        if len(chunk) < page_size:
            break

    # Fetch invoices in the date range
    matrix: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    totals_month: dict[str, Decimal] = defaultdict(Decimal)
    totals_group: dict[str, Decimal] = defaultdict(Decimal)
    grand = Decimal("0")
    invoice_count = 0

    for page in range(max_pages):
        chunk = await client.list_verkoopfacturen(
            from_date=start, top=page_size, skip=page * page_size,
        )
        if not chunk:
            break
        for f in chunk:
            mkey = _month_key(f.get("factuurdatum") or f.get("Factuurdatum"))
            if not mkey or mkey not in month_labels:
                continue
            gid = _factuur_groep_id(f, relaties_index) or "ZONDER_GROEP"
            amt = _factuur_amount(f)
            matrix[gid][mkey] += amt
            totals_month[mkey] += amt
            totals_group[gid] += amt
            grand += amt
            invoice_count += 1
        if len(chunk) < page_size:
            break

    # Build group descriptors (only groups that actually had invoices,
    # plus the special "ZONDER_GROEP" bucket if used)
    groups_out: list[dict[str, Any]] = []
    seen_gids = set(matrix.keys())
    for gid in seen_gids:
        if gid == "ZONDER_GROEP":
            groups_out.append({"id": "ZONDER_GROEP", "naam": "(geen groep)"})
        else:
            g = groep_index.get(gid, {})
            groups_out.append({
                "id": gid,
                "naam": g.get("naam") or g.get("name") or f"Groep {gid[:8]}",
            })
    # Sort: largest total first
    groups_out.sort(key=lambda x: -float(totals_group.get(x["id"], 0)))

    # Serialize Decimals
    def f2(d: Decimal) -> float:
        return float(d.quantize(Decimal("0.01")))

    return {
        "months": month_labels,
        "groups": groups_out,
        "matrix": {
            gid: {m: f2(matrix[gid][m]) for m in month_labels}
            for gid in matrix
        },
        "totals_per_month": {m: f2(totals_month[m]) for m in month_labels},
        "totals_per_group": {gid: f2(totals_group[gid]) for gid in matrix},
        "grand_total": f2(grand),
        "invoice_count": invoice_count,
        "from_date": start.isoformat(),
        "to_date": now.isoformat(),
    }
