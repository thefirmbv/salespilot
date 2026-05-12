"""HaloPSA quotations sync.

We fetch every quotation in HaloPSA in a single call (`include_details=true`
gives us status, expiry_date, total, cost, profit, revenue and timestamps),
then group by `client_id` and match each one against the local Company
record (by `halopsa_id`).

For each quotation we:
  - map HaloPSA's status enum to our internal status ('draft' | 'sent' |
    'accepted' | 'rejected' | 'expired')
  - auto-link a Deal (existing single-open-deal, otherwise create one)
  - schedule reminder activities at day 14 and 28 (only for status=sent
    with a known sent_at)

Status mapping comes from a small dict that maps the HaloPSA `status` int
to our enum value. If the tenant has customised statuses, the mapping may
need adjustment — we log unmapped values via `status_label_halopsa` so
they remain visible in the UI.

HaloPSA stores the placeholder '1899-12-30T00:00:00' for "never". We
strip those before parsing.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from salespilot.integrations.halopsa import HaloPSAClient, HaloPSAError
from salespilot.models.crm import (
    Activity,
    ActivityTarget,
    ActivityType,
    Company,
    Deal,
)
from salespilot.models.quotation import Quotation


# HaloPSA uses TWO fields to encode quotation state:
#   `status`        : sales-side workflow (0=concept/sent, 3=sent (variant),
#                     6=closed/superseded, 4=hidden expiry, …)
#   `approvalstate` : internal sign-off state (0=none, 1=pending, 2=approved)
#
# Combined into our 5-state model:
#   `accepted` : approvalstate == 2 (internally approved and signed back)
#   `draft`    : status 0 with no approvalstate movement yet
#   `sent`     : actively waiting on the customer
#   `expired`  : sent_at older than EXPIRY_DAYS but younger than REJECT_DAYS
#   `rejected` : status 6 OR sent_at older than REJECT_DAYS months
#
# These rules were calibrated on IT-Gemak's HaloPSA data + manual verification
# (e.g. Girasol's "Modern Workspace" id=230 → status=3, approvalstate=1, sent
# 2026-05-08 → must be SENT/open).

EXPIRY_DAYS = 30   # offerte loopt 30 dagen
REJECT_DAYS = 90   # > 3 maanden zonder reactie = praktisch afgewezen


def _map_status(
    *,
    status: Any,
    approvalstate: Any,
    sent_at: datetime | None,
    now: datetime,
) -> str:
    # Hard signal: internally approved → won.
    if isinstance(approvalstate, int) and approvalstate == 2:
        return "accepted"

    # status=6 is HaloPSA's "closed/cancelled" — treat as rejected.
    if isinstance(status, int) and status == 6:
        return "rejected"

    # Age-based override per user request: anything older than 3 months
    # without a positive outcome is effectively rejected.
    if sent_at is not None:
        age = now - sent_at
        if age.days >= REJECT_DAYS:
            return "rejected"
        if age.days >= EXPIRY_DAYS:
            return "expired"

    # Active sent: status 1, 2, 3, or 4 with approvalstate in (0,1) means
    # the quotation is out with the customer.
    if isinstance(status, int) and status in (1, 2, 3, 4):
        return "sent"

    # status=0 catches both "just created" and "draft, not yet decided".
    # Without sent_at age we treat it as draft.
    return "draft"


def _parse_dt(v: Any) -> datetime | None:
    if not v or not isinstance(v, str):
        return None
    s = v.strip()
    if not s or s.startswith("1899-12-30"):
        # HaloPSA's placeholder for "never set"
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return None


def _parse_amount(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v)).quantize(Decimal("0.01"))
    except (ValueError, ArithmeticError):
        return None


def _map_payload(raw: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    status_int = raw.get("status")
    approvalstate = raw.get("approvalstate")
    sent_at = _parse_dt(raw.get("date"))  # creation date in HaloPSA
    expiry = _parse_dt(raw.get("expiry_date"))
    approved_at = _parse_dt(raw.get("approvaldatetime"))
    status = _map_status(
        status=status_int, approvalstate=approvalstate, sent_at=sent_at, now=now
    )
    return {
        "reference": raw.get("ref") or raw.get("title") or (str(raw["id"]) if "id" in raw else None),
        "subject": raw.get("title") or raw.get("subject") or raw.get("scope") or "",
        "status": status,
        "status_id_halopsa": status_int if isinstance(status_int, int) else None,
        "status_label_halopsa": (
            f"halo s={status_int} a={approvalstate}"
            if isinstance(status_int, int)
            else None
        ),
        # HaloPSA fields:
        #   - total = gross incl. tax (sometimes null)
        #   - revenue = net excl. tax (the line items sum)
        # We fall back to revenue when total is missing, so the UI always
        # has *something* to display.
        "amount_net": _parse_amount(raw.get("revenue")),
        "amount_gross": _parse_amount(raw.get("total") or raw.get("revenue")),
        "currency": "EUR",  # HaloPSA returns the symbol in 'currency'; safe default
        "sent_at": sent_at,
        "valid_until": expiry,
        "accepted_at": approved_at if status == "accepted" else None,
        "rejected_at": approved_at if status == "rejected" else None,
    }


def _is_open(status: str) -> bool:
    return status in {"draft", "sent"}


class _NoDealCreated(Exception):
    pass


async def _ensure_deal_for_quotation(
    db: AsyncSession,
    *,
    org_id: UUID,
    company: Company,
    quotation_subject: str | None,
    amount: Decimal | None,
    status: str,
    quotation_halopsa_id: int,
) -> tuple[Deal, bool]:
    """Pick or create a Deal to attach this quotation to (Option A: auto-link).

    Lookup order (most specific first):
      1. The deal that this quotation is *already* linked to (returned via
         row.deal_id from the caller — handled there, not here)
      2. A single open Deal for this company -> reuse
      3. Multiple open Deals -> pick the most recently updated
      4. Otherwise, fall through to creating a new Deal

    NOTE: we never re-create a Deal just because there are no more *open*
    deals — if a Deal already exists for this company we keep linking new
    quotations to it (it will be re-opened during _recompute_deal_statuses
    if any quotation is still open).
    """
    # 1) Prefer an existing OPEN deal for this company.
    open_deals = (
        await db.execute(
            select(Deal).where(Deal.company_id == company.id, Deal.status == "open")
        )
    ).scalars().all()
    if len(open_deals) == 1:
        return open_deals[0], False
    if len(open_deals) > 1:
        return max(open_deals, key=lambda d: d.updated_at or d.created_at), False

    # 2) No open deal but maybe the company already has a *closed* deal we
    # can reuse for a new quotation (so we don't keep duplicating deals on
    # every sync). Only reuse a closed deal if the new quotation is also
    # closed (accepted/rejected/expired) — otherwise create a fresh open
    # deal for the new active quotation.
    if not _is_open(status):
        any_deals = (
            await db.execute(
                select(Deal).where(Deal.company_id == company.id)
                .order_by(Deal.updated_at.desc())
                .limit(1)
            )
        ).scalars().all()
        if any_deals:
            return any_deals[0], False

    # 3) Otherwise create a new Deal.
    from salespilot.models.crm import Pipeline, Stage

    pipeline = (
        await db.execute(select(Pipeline).order_by(Pipeline.created_at.asc()).limit(1))
    ).scalar_one_or_none()
    if pipeline is None:
        raise _NoDealCreated()
    first_stage = (
        await db.execute(
            select(Stage)
            .where(Stage.pipeline_id == pipeline.id)
            .order_by(Stage.position.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if first_stage is None:
        raise _NoDealCreated()

    deal_status = "open" if _is_open(status) else ("won" if status == "accepted" else "lost")
    deal = Deal(
        id=uuid4(),
        org_id=org_id,
        pipeline_id=pipeline.id,
        stage_id=first_stage.id,
        company_id=company.id,
        name=(quotation_subject or f"Offerte voor {company.name}")[:200],
        amount=amount,
        currency="EUR",
        status=deal_status,
    )
    db.add(deal)
    await db.flush()
    return deal, True


async def _ensure_reminders(
    db: AsyncSession,
    *,
    org_id: UUID,
    quotation: Quotation,
    company: Company,
) -> int:
    """Idempotent reminder creation at day 14 + day 28 after sent_at."""
    if quotation.status != "sent" or quotation.sent_at is None:
        return 0
    targets = [
        ("quote_followup_14d", quotation.sent_at + timedelta(days=14), "Nabellen offerte"),
        ("quote_followup_28d", quotation.sent_at + timedelta(days=28), "Laatste check vóór verlopen"),
    ]
    created = 0
    ref_str = quotation.reference or f"#{quotation.halopsa_id}"
    body_lines = [f"Offerte {ref_str} naar {company.name}."]
    if quotation.amount_gross is not None:
        body_lines.append(f"Bedrag: {quotation.currency} {quotation.amount_gross}")
    if quotation.valid_until is not None:
        body_lines.append(
            f"Geldig tot: {quotation.valid_until.date().isoformat()}"
        )
    body = "\n".join(body_lines)

    for kind, due_at, subject_prefix in targets:
        existing = (
            await db.execute(
                select(Activity).where(
                    Activity.quotation_id == quotation.id,
                    Activity.reminder_kind == kind,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            # Keep existing; just update due_at if quotation sent_at shifted.
            if existing.completed_at is None and existing.due_at != due_at:
                existing.due_at = due_at
            continue
        db.add(
            Activity(
                id=uuid4(),
                org_id=org_id,
                type=ActivityType.CALL,
                target_type=ActivityTarget.COMPANY,
                target_id=company.id,
                subject=f"{subject_prefix} {ref_str}",
                body=body,
                due_at=due_at,
                completed_at=None,
                author_id=None,
                quotation_id=quotation.id,
                reminder_kind=kind,
            )
        )
        created += 1
    return created


async def sync_quotations_for_org(
    db: AsyncSession,
    *,
    org_id: UUID,
    halopsa_client: HaloPSAClient,
) -> dict[str, int]:
    """Fetch all quotations in one HaloPSA call, then upsert."""
    fetched = 0
    created = 0
    updated = 0
    deals_created = 0
    reminders = 0
    skipped_no_company = 0

    try:
        quotations = await halopsa_client.list_all_quotations()
    except HaloPSAError:
        return {
            "fetched": 0, "created": 0, "updated": 0,
            "deals_created": 0, "reminders_scheduled": 0,
            "skipped_no_company": 0,
        }

    # Index local companies by halopsa_id for O(1) lookup.
    companies = (
        await db.execute(
            select(Company).where(Company.halopsa_id.is_not(None))
        )
    ).scalars().all()
    by_halopsa_id: dict[int, Company] = {
        c.halopsa_id: c for c in companies if c.halopsa_id is not None
    }

    now = datetime.now(UTC)

    for raw in quotations:
        halopsa_id = raw.get("id")
        if not isinstance(halopsa_id, int):
            try:
                halopsa_id = int(halopsa_id)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
        fetched += 1

        client_id = raw.get("client_id")
        if not isinstance(client_id, int):
            skipped_no_company += 1
            continue
        company = by_halopsa_id.get(client_id)
        if company is None:
            # Quotation in HaloPSA for a client we haven't synced yet.
            # Skip rather than fail; will pick up after next halopsa-sync.
            skipped_no_company += 1
            continue

        mapped = _map_payload(raw, now=now)

        row = (
            await db.execute(
                select(Quotation).where(
                    Quotation.org_id == org_id,
                    Quotation.halopsa_id == halopsa_id,
                )
            )
        ).scalar_one_or_none()

        # Auto-link Deal
        deal_id: UUID | None = None
        try:
            deal, was_created = await _ensure_deal_for_quotation(
                db,
                org_id=org_id,
                company=company,
                quotation_subject=mapped["subject"],
                amount=mapped["amount_gross"] or mapped["amount_net"],
                status=mapped["status"],
                quotation_halopsa_id=halopsa_id,
            )
            deal_id = deal.id
            if was_created:
                deals_created += 1
        except _NoDealCreated:
            pass

        if row is None:
            row = Quotation(
                id=uuid4(),
                org_id=org_id,
                company_id=company.id,
                deal_id=deal_id,
                halopsa_id=halopsa_id,
                raw=raw,
                synced_at=now,
                **mapped,
            )
            db.add(row)
            await db.flush()
            created += 1
        else:
            for k, v in mapped.items():
                setattr(row, k, v)
            if deal_id is not None and row.deal_id is None:
                row.deal_id = deal_id
            row.raw = raw
            row.synced_at = now
            updated += 1

        reminders += await _ensure_reminders(
            db, org_id=org_id, quotation=row, company=company
        )

    # After upserting every quotation, recompute the deal status for the
    # affected deals so that deal.status reflects the *best* outcome
    # across all linked quotations (a single accepted quote wins the deal,
    # all rejected/expired loses it, otherwise it stays open).
    deals_recomputed = await _recompute_deal_statuses(db, org_id=org_id)

    return {
        "fetched": fetched,
        "created": created,
        "updated": updated,
        "deals_created": deals_created,
        "reminders_scheduled": reminders,
        "skipped_no_company": skipped_no_company,
        "deals_recomputed": deals_recomputed,
    }


async def _recompute_deal_statuses(
    db: AsyncSession, *, org_id: UUID
) -> int:
    """Walk every deal that has at least one linked quotation and reset its
    status + amount based on those quotations.

    Rules:
      - any quotation with status='accepted' -> deal won, closed_at = the
        accepted_at of that quote
      - else if all quotations are rejected/expired -> deal lost
      - else -> deal open
      - amount = max amount_gross|amount_net over the quotations (we prefer
        the highest because that's typically the latest/most-complete one)
    """
    from salespilot.models.crm import DealStatus

    from salespilot.models.crm import Stage

    # Pre-load all stages per pipeline so we can map status -> stage_id
    # without N+1 lookups during the deal loop.
    all_stages = (await db.execute(select(Stage))).scalars().all()
    pipeline_stages: dict[UUID, list[Stage]] = {}
    for s in all_stages:
        pipeline_stages.setdefault(s.pipeline_id, []).append(s)
    for pid in pipeline_stages:
        pipeline_stages[pid].sort(key=lambda s: s.position)

    deals = (
        await db.execute(
            select(Deal).where(Deal.org_id == org_id)
        )
    ).scalars().all()
    changed = 0
    for deal in deals:
        quotes = (
            await db.execute(
                select(Quotation).where(Quotation.deal_id == deal.id)
            )
        ).scalars().all()
        if not quotes:
            continue
        statuses = {q.status for q in quotes}
        amounts = [q.amount_gross or q.amount_net or Decimal("0") for q in quotes]
        accepted_quotes = [q for q in quotes if q.status == "accepted"]

        if accepted_quotes:
            target_status = DealStatus.WON
            # closed_at = latest accepted_at among the accepted quotes
            target_closed = max(
                (q.accepted_at for q in accepted_quotes if q.accepted_at),
                default=None,
            )
            # For won deals, the amount is the sum of accepted quote amounts.
            target_amount = sum(
                (q.amount_gross or q.amount_net or Decimal("0") for q in accepted_quotes),
                start=Decimal("0"),
            )
        elif statuses and statuses.issubset({"rejected", "expired"}):
            target_status = DealStatus.LOST
            # Use the most recent rejected_at as closed_at
            target_closed = max(
                (q.rejected_at for q in quotes if q.rejected_at),
                default=None,
            )
            target_amount = max(amounts) if amounts else Decimal("0")
        else:
            target_status = DealStatus.OPEN
            target_closed = None
            target_amount = max(amounts) if amounts else Decimal("0")

        cur_status = deal.status.value if hasattr(deal.status, "value") else str(deal.status)
        want_status_str = target_status.value
        target_stage_id = _stage_id_for_status(deal.pipeline_id, target_status, pipeline_stages)
        if (
            cur_status != want_status_str
            or deal.amount != target_amount
            or deal.closed_at != target_closed
            or (target_stage_id is not None and deal.stage_id != target_stage_id)
        ):
            deal.status = target_status
            deal.amount = target_amount
            deal.closed_at = target_closed
            if target_stage_id is not None:
                deal.stage_id = target_stage_id
            changed += 1

    await db.flush()
    return changed


def _stage_id_for_status(
    pipeline_id: UUID, status: "DealStatus", stages_by_pipeline: dict
) -> UUID | None:
    """Pick the appropriate stage for a deal's new status.

    For won -> first stage with is_won=True (or last position)
    For lost -> first stage with is_lost=True (or last position)
    For open -> leave stage unchanged (we don't know which stage)
    """
    from salespilot.models.crm import DealStatus

    stages = stages_by_pipeline.get(pipeline_id, [])
    if not stages:
        return None
    if status == DealStatus.WON:
        won = [s for s in stages if getattr(s, "is_won", False)]
        return won[0].id if won else None
    if status == DealStatus.LOST:
        lost = [s for s in stages if getattr(s, "is_lost", False)]
        return lost[0].id if lost else None
    return None  # open: don't change
