"""HaloPSA Mail Campaigns sync.

Fetches every campaign + its recipient list, maps HaloPSA's status enum
into our 6-state model, denormalises aggregate counters onto the campaign
row, and inserts/upserts a recipient row per (campaign × email).

Status mapping in HaloPSA varies a bit by tenant; we use a name-first
strategy with a fallback to status int, so re-running sync is safe even
when a tenant tweaks status labels.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from salespilot.integrations.halopsa import HaloPSAClient, HaloPSAError
from salespilot.models.crm import Company, Contact
from salespilot.models.mail_campaign import MailCampaign, MailCampaignRecipient


_CAMPAIGN_STATUS_NAMES = {
    "draft": "draft",
    "scheduled": "scheduled",
    "queued": "scheduled",
    "sending": "sending",
    "in progress": "sending",
    "sent": "sent",
    "completed": "sent",
    "complete": "sent",
    "paused": "paused",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "stopped": "cancelled",
}

# Per-recipient status names (HaloPSA uses different vocabulary here).
_RECIPIENT_STATUS_NAMES = {
    "queued": "queued",
    "pending": "queued",
    "sent": "sent",
    "delivered": "delivered",
    "opened": "opened",
    "clicked": "clicked",
    "bounced": "bounced",
    "complained": "complained",
    "spam": "complained",
    "unsubscribed": "unsubscribed",
    "opted out": "unsubscribed",
    "optout": "unsubscribed",
    "failed": "failed",
    "error": "failed",
}


def _normalise_status(name: Any, mapping: dict[str, str], default: str) -> str:
    if isinstance(name, str):
        lower = name.strip().lower()
        if lower in mapping:
            return mapping[lower]
    return default


def _parse_dt(v: Any) -> datetime | None:
    if not v or not isinstance(v, str):
        return None
    s = v.strip()
    if not s or s.startswith("1899-12-30"):
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


def _int_or_zero(v: Any) -> int:
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        try:
            return int(v)
        except ValueError:
            return 0
    return 0


def _map_campaign(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": raw.get("name") or raw.get("title") or f"Campagne #{raw.get('id', '?')}",
        "subject": raw.get("subject"),
        "from_name": raw.get("fromname") or raw.get("from_name") or raw.get("sender_name"),
        "from_email": raw.get("fromemail") or raw.get("from_email") or raw.get("sender_email"),
        "status": _normalise_status(
            raw.get("status_name") or raw.get("status"),
            _CAMPAIGN_STATUS_NAMES,
            "draft",
        ),
        "status_label_halopsa": raw.get("status_name") or raw.get("status"),
        "sent_at": _parse_dt(raw.get("sent_date") or raw.get("date_sent") or raw.get("senddate")),
        "scheduled_at": _parse_dt(raw.get("schedule_date") or raw.get("scheduled") or raw.get("dateschedule")),
        # HaloPSA tends to expose counters as flat ints
        "recipients_total": _int_or_zero(raw.get("recipients_total") or raw.get("total_recipients") or raw.get("count")),
        "sent_count": _int_or_zero(raw.get("sent") or raw.get("sent_count")),
        "delivered_count": _int_or_zero(raw.get("delivered") or raw.get("delivered_count")),
        "opened_count": _int_or_zero(raw.get("opens") or raw.get("opened") or raw.get("opened_count") or raw.get("open_count")),
        "clicked_count": _int_or_zero(raw.get("clicks") or raw.get("clicked") or raw.get("clicked_count") or raw.get("click_count")),
        "bounced_count": _int_or_zero(raw.get("bounces") or raw.get("bounced") or raw.get("bounced_count")),
        "unsubscribed_count": _int_or_zero(raw.get("unsubscribes") or raw.get("unsubscribed") or raw.get("optout_count")),
        "complained_count": _int_or_zero(raw.get("complaints") or raw.get("complained")),
    }


def _map_recipient(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "email": (raw.get("email") or raw.get("emailaddress") or raw.get("to") or "").strip(),
        "name": raw.get("name") or raw.get("display_name"),
        "status": _normalise_status(
            raw.get("status_name") or raw.get("status"),
            _RECIPIENT_STATUS_NAMES,
            "queued",
        ),
        "sent_at": _parse_dt(raw.get("sent_at") or raw.get("date_sent") or raw.get("senddate")),
        "delivered_at": _parse_dt(raw.get("delivered_at") or raw.get("delivereddate")),
        "opened_at": _parse_dt(raw.get("opened_at") or raw.get("openeddate") or raw.get("first_open")),
        "clicked_at": _parse_dt(raw.get("clicked_at") or raw.get("clickeddate") or raw.get("first_click")),
        "bounced_at": _parse_dt(raw.get("bounced_at") or raw.get("bouncedate")),
        "unsubscribed_at": _parse_dt(raw.get("unsubscribed_at") or raw.get("optoutdate")),
        "open_count": _int_or_zero(raw.get("open_count") or raw.get("opens")),
        "click_count": _int_or_zero(raw.get("click_count") or raw.get("clicks")),
        "halopsa_recipient_id": raw.get("id") if isinstance(raw.get("id"), int) else None,
    }


async def sync_mail_campaigns_for_org(
    db: AsyncSession,
    *,
    org_id: UUID,
    halopsa_client: HaloPSAClient,
) -> dict[str, int]:
    """Pull every mail campaign + its recipients from HaloPSA."""
    fetched = 0
    created = 0
    updated = 0
    recipients_synced = 0
    no_permission = False

    try:
        raw_campaigns = await halopsa_client.list_mail_campaigns()
    except HaloPSAError:
        raw_campaigns = []

    if not raw_campaigns:
        # Either zero campaigns or no permission — caller decides what to
        # do with that information.
        return {
            "fetched": 0, "created": 0, "updated": 0,
            "recipients_synced": 0, "no_permission": 1,
        }

    # Index local contacts by email for company linking.
    contacts_by_email: dict[str, Contact] = {}
    for c in (await db.execute(select(Contact))).scalars():
        if c.email:
            contacts_by_email[c.email.lower()] = c
    companies_by_halopsa: dict[int, Company] = {}
    for c in (
        await db.execute(select(Company).where(Company.halopsa_id.is_not(None)))
    ).scalars():
        if c.halopsa_id is not None:
            companies_by_halopsa[c.halopsa_id] = c

    now = datetime.now(UTC)

    for raw in raw_campaigns:
        halopsa_id = raw.get("id")
        if not isinstance(halopsa_id, int):
            try:
                halopsa_id = int(halopsa_id)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
        fetched += 1
        mapped = _map_campaign(raw)

        row = (
            await db.execute(
                select(MailCampaign).where(
                    MailCampaign.org_id == org_id,
                    MailCampaign.halopsa_id == halopsa_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = MailCampaign(
                id=uuid4(),
                org_id=org_id,
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
            row.raw = raw
            row.synced_at = now
            updated += 1

        # Pull recipients. List endpoint may include recipients inline
        # ('recipients' key) or require a detail-fetch.
        recipients_raw: list[dict[str, Any]] = []
        if isinstance(raw.get("recipients"), list):
            recipients_raw = raw["recipients"]
        else:
            detail = await halopsa_client.get_mail_campaign(halopsa_id)
            if isinstance(detail, dict):
                if isinstance(detail.get("recipients"), list):
                    recipients_raw = detail["recipients"]

        # Upsert per (campaign_id, email).
        seen: set[str] = set()
        existing_rcpts = {
            r.email.lower(): r
            for r in (
                await db.execute(
                    select(MailCampaignRecipient).where(
                        MailCampaignRecipient.campaign_id == row.id
                    )
                )
            ).scalars()
        }

        for r_raw in recipients_raw:
            rmap = _map_recipient(r_raw)
            email = rmap["email"]
            if not email:
                continue
            seen.add(email.lower())

            # Try to link to a local contact + its company.
            contact = contacts_by_email.get(email.lower())
            company_id: UUID | None = None
            contact_id: UUID | None = None
            if contact is not None:
                contact_id = contact.id
                company_id = contact.company_id
            # Fallback: HaloPSA may include client_id directly on the
            # recipient row.
            if company_id is None and isinstance(r_raw.get("client_id"), int):
                local_company = companies_by_halopsa.get(r_raw["client_id"])
                if local_company is not None:
                    company_id = local_company.id

            existing = existing_rcpts.get(email.lower())
            if existing is None:
                db.add(
                    MailCampaignRecipient(
                        id=uuid4(),
                        org_id=org_id,
                        campaign_id=row.id,
                        company_id=company_id,
                        contact_id=contact_id,
                        raw=r_raw,
                        **rmap,
                    )
                )
                recipients_synced += 1
            else:
                for k, v in rmap.items():
                    setattr(existing, k, v)
                if company_id is not None and existing.company_id is None:
                    existing.company_id = company_id
                if contact_id is not None and existing.contact_id is None:
                    existing.contact_id = contact_id
                existing.raw = r_raw
                recipients_synced += 1

    await db.flush()
    return {
        "fetched": fetched,
        "created": created,
        "updated": updated,
        "recipients_synced": recipients_synced,
        "no_permission": 0,
    }
