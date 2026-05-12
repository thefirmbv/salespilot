"""API for HaloPSA mail campaigns: list, detail, recipients, sync, KPI summary.

Read-only to clients — the actual campaign authoring lives in HaloPSA.
We keep an idempotent sync trigger (POST /mail-campaigns/sync) and a
per-campaign recipients lookup for the detail page.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from salespilot.deps import CurrentAuth, Db
from salespilot.integrations.halopsa import HaloPSAClient, HaloPSACredentials, HaloPSAError
from salespilot.integrations.halopsa_mail_campaigns import sync_mail_campaigns_for_org
from salespilot.models.crm import Company, Contact
from salespilot.models.integrations import Integration
from salespilot.models.mail_campaign import MailCampaign, MailCampaignRecipient
from salespilot.schemas.mail_campaign import (
    MailCampaignPublic,
    MailCampaignRecipientPublic,
    MailCampaignsSummary,
    MailCampaignSyncResult,
)

router = APIRouter(prefix="/mail-campaigns", tags=["mail-campaigns"])


def _halopsa_creds(row: Integration) -> HaloPSACredentials:
    cfg = row.config_json or {}
    return HaloPSACredentials(
        base_url=cfg.get("base_url", ""),
        client_id=cfg.get("client_id", ""),
        client_secret=cfg.get("client_secret", ""),
        tenant=cfg.get("tenant"),
        scopes=cfg.get("scopes") or "all",
    )


def _enrich(c: MailCampaign) -> MailCampaignPublic:
    p = MailCampaignPublic.model_validate(c)
    denom = c.delivered_count or c.sent_count or c.recipients_total or 0
    if denom > 0:
        p.open_rate = round(c.opened_count / denom * 100, 1)
        p.click_rate = round(c.clicked_count / denom * 100, 1)
        sent_denom = c.sent_count or c.recipients_total or 0
        p.bounce_rate = round(c.bounced_count / sent_denom * 100, 1) if sent_denom > 0 else 0.0
    return p


@router.get("", response_model=list[MailCampaignPublic])
async def list_campaigns(
    auth: CurrentAuth,
    db: Db,
    status: str | None = Query(None),
    limit: int = Query(200, le=500),
) -> list[MailCampaignPublic]:
    stmt = select(MailCampaign)
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            stmt = stmt.where(MailCampaign.status.in_(statuses))
    stmt = stmt.order_by(
        MailCampaign.sent_at.desc().nullslast(),
        MailCampaign.scheduled_at.desc().nullslast(),
        MailCampaign.updated_at.desc(),
    ).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [_enrich(c) for c in rows]


@router.get("/summary", response_model=MailCampaignsSummary)
async def campaigns_summary(auth: CurrentAuth, db: Db) -> MailCampaignsSummary:
    now = datetime.now(UTC)
    thirty = now - timedelta(days=30)

    rows = (await db.execute(select(MailCampaign))).scalars().all()
    total = len(rows)
    last_30d = [c for c in rows if c.sent_at and c.sent_at >= thirty]

    recipients = sum(c.recipients_total for c in last_30d)
    delivered = sum(c.delivered_count for c in last_30d)
    opened = sum(c.opened_count for c in last_30d)
    clicked = sum(c.clicked_count for c in last_30d)
    bounced = sum(c.bounced_count for c in last_30d)

    # Open/click rate per campaign averaged across campaigns (not weighted)
    if last_30d:
        open_rates = []
        click_rates = []
        bounce_rates = []
        for c in last_30d:
            denom = c.delivered_count or c.sent_count or c.recipients_total or 0
            if denom > 0:
                open_rates.append(c.opened_count / denom * 100)
                click_rates.append(c.clicked_count / denom * 100)
            sent_denom = c.sent_count or c.recipients_total or 0
            if sent_denom > 0:
                bounce_rates.append(c.bounced_count / sent_denom * 100)
        avg_open = round(sum(open_rates) / len(open_rates), 1) if open_rates else 0.0
        avg_click = round(sum(click_rates) / len(click_rates), 1) if click_rates else 0.0
        avg_bounce = round(sum(bounce_rates) / len(bounce_rates), 1) if bounce_rates else 0.0
    else:
        avg_open = avg_click = avg_bounce = 0.0

    return MailCampaignsSummary(
        total_campaigns=total,
        campaigns_last_30d=len(last_30d),
        recipients_total_30d=recipients,
        delivered_30d=delivered,
        opened_30d=opened,
        clicked_30d=clicked,
        bounced_30d=bounced,
        avg_open_rate_30d=avg_open,
        avg_click_rate_30d=avg_click,
        avg_bounce_rate_30d=avg_bounce,
    )


@router.get("/{campaign_id}", response_model=MailCampaignPublic)
async def get_campaign(campaign_id: UUID, auth: CurrentAuth, db: Db) -> MailCampaignPublic:
    c = await db.get(MailCampaign, campaign_id)
    if c is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    return _enrich(c)


@router.get(
    "/{campaign_id}/recipients", response_model=list[MailCampaignRecipientPublic]
)
async def list_recipients(
    campaign_id: UUID,
    auth: CurrentAuth,
    db: Db,
    status: str | None = Query(None),
    limit: int = Query(500, le=2000),
) -> list[MailCampaignRecipientPublic]:
    c = await db.get(MailCampaign, campaign_id)
    if c is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    stmt = select(MailCampaignRecipient).where(
        MailCampaignRecipient.campaign_id == campaign_id
    )
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            stmt = stmt.where(MailCampaignRecipient.status.in_(statuses))
    # Most interesting first: clicked > opened > delivered > sent > bounced > queued.
    stmt = stmt.order_by(
        MailCampaignRecipient.clicked_at.desc().nullslast(),
        MailCampaignRecipient.opened_at.desc().nullslast(),
        MailCampaignRecipient.delivered_at.desc().nullslast(),
        MailCampaignRecipient.sent_at.desc().nullslast(),
    ).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return []

    company_ids = {r.company_id for r in rows if r.company_id}
    contact_ids = {r.contact_id for r in rows if r.contact_id}
    companies = {}
    contacts = {}
    if company_ids:
        for x in (await db.execute(select(Company).where(Company.id.in_(company_ids)))).scalars():
            companies[x.id] = x.name
    if contact_ids:
        for x in (await db.execute(select(Contact).where(Contact.id.in_(contact_ids)))).scalars():
            parts = [x.first_name, x.last_name]
            contacts[x.id] = " ".join(p for p in parts if p).strip() or None

    out: list[MailCampaignRecipientPublic] = []
    for r in rows:
        p = MailCampaignRecipientPublic.model_validate(r)
        p.company_name = companies.get(r.company_id) if r.company_id else None
        p.contact_name = contacts.get(r.contact_id) if r.contact_id else None
        out.append(p)
    return out


@router.post("/sync", response_model=MailCampaignSyncResult)
async def sync_campaigns(auth: CurrentAuth, db: Db) -> MailCampaignSyncResult:
    integ = (
        await db.execute(select(Integration).where(Integration.kind == "halopsa"))
    ).scalar_one_or_none()
    if integ is None or not integ.is_enabled:
        raise HTTPException(status_code=400, detail="HaloPSA not configured or disabled")

    try:
        async with HaloPSAClient(_halopsa_creds(integ)) as client:
            counters = await sync_mail_campaigns_for_org(
                db, org_id=auth.org_id, halopsa_client=client
            )
    except HaloPSAError as e:
        return MailCampaignSyncResult(ok=False, detail=str(e))

    if counters.get("no_permission") and counters.get("fetched", 0) == 0:
        return MailCampaignSyncResult(
            ok=False,
            detail=(
                "HaloPSA API permission ontbreekt voor Mail Campaigns. "
                "Voeg 'Mail Campaign' (Read) toe aan de SalesPilot API-app "
                "in HaloPSA: Configuration \u2192 Integrations \u2192 API \u2192 Applications."
            ),
        )
    return MailCampaignSyncResult(
        ok=True,
        detail=(
            f"Synced {counters['fetched']} campagnes "
            f"({counters['created']} nieuw, {counters['updated']} bijgewerkt, "
            f"{counters['recipients_synced']} ontvangers)"
        ),
        fetched=counters["fetched"],
        created=counters["created"],
        updated=counters["updated"],
        recipients_synced=counters["recipients_synced"],
    )
