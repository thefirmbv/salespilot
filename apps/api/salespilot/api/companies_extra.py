"""Extra company endpoints: per-company communications timeline.

Aggregates ALL outbound + inbound communication for a given company
across:
  * HaloPSA mail campaign recipients (MailCampaignRecipient)
  * Sequence emails sent via autopilot (Message rows joined through
    Enrollment.company_id)
  * LinkedIn posts that have a destination matching the company's
    LinkedIn organization URN
  * LinkedIn outreach tasks targeted at this company

Each entry is normalised to a Timeline shape with engagement state so
the UI can render a uniform list.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from salespilot.deps import CurrentAuth, Db
from salespilot.models.autopilot import Enrollment, LinkedInTask, Message
from salespilot.models.crm import Company, Contact
from salespilot.models.mail_campaign import MailCampaign, MailCampaignRecipient
from salespilot.models.social import SocialPost


router = APIRouter(prefix="/companies", tags=["companies"])


class CommunicationEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: Literal[
        "campaign_mail",
        "sequence_mail",
        "linkedin_post",
        "linkedin_task",
    ]
    direction: Literal["outbound", "inbound"] = "outbound"
    subject: str | None = None
    snippet: str | None = None
    to_name: str | None = None
    to_email: str | None = None
    sent_at: datetime | None = None
    # Engagement state for emails
    delivered_at: datetime | None = None
    opened_at: datetime | None = None
    clicked_at: datetime | None = None
    bounced_at: datetime | None = None
    status: str | None = None
    # Linking
    campaign_id: str | None = None
    post_id: str | None = None
    external_url: str | None = None


class CommunicationsResponse(BaseModel):
    company_id: UUID
    total: int = 0
    entries: list[CommunicationEntry] = []
    # Quick summary for the UI badge
    last_outbound_at: datetime | None = None
    last_open_at: datetime | None = None
    open_count: int = 0
    click_count: int = 0


class CompanyCommsBadge(BaseModel):
    company_id: UUID
    last_outbound_at: datetime | None = None
    last_open_at: datetime | None = None
    sent_count: int = 0
    open_count: int = 0
    click_count: int = 0
    bounced_count: int = 0


@router.get("/communications-summary", response_model=list[CompanyCommsBadge])
async def communications_summary(auth: CurrentAuth, db: Db) -> list[CompanyCommsBadge]:
    """One-row-per-company summary of mail engagement.

    Used by the Companies overview page to render quick badges next to
    each company name. Cheap aggregate query over mail_campaign_recipients;
    sequence Messages are added in a second pass joined via Enrollment.
    """
    from sqlalchemy import func

    badges: dict[UUID, CompanyCommsBadge] = {}

    # Mail campaign recipients aggregate
    rcpt_rows = (
        await db.execute(
            select(
                MailCampaignRecipient.company_id,
                func.count(MailCampaignRecipient.id).label("sent"),
                func.max(MailCampaignRecipient.sent_at).label("last_sent"),
                func.max(MailCampaignRecipient.opened_at).label("last_open"),
                func.count(MailCampaignRecipient.opened_at).label("opens"),
                func.count(MailCampaignRecipient.clicked_at).label("clicks"),
                func.count(MailCampaignRecipient.bounced_at).label("bounces"),
            )
            .where(MailCampaignRecipient.company_id.is_not(None))
            .group_by(MailCampaignRecipient.company_id)
        )
    ).all()
    for r in rcpt_rows:
        if r.company_id is None:
            continue
        badges[r.company_id] = CompanyCommsBadge(
            company_id=r.company_id,
            last_outbound_at=r.last_sent,
            last_open_at=r.last_open,
            sent_count=int(r.sent or 0),
            open_count=int(r.opens or 0),
            click_count=int(r.clicks or 0),
            bounced_count=int(r.bounces or 0),
        )

    # Sequence messages aggregate, joined through Enrollment.company_id
    msg_rows = (
        await db.execute(
            select(
                Enrollment.company_id,
                func.count(Message.id).label("sent"),
                func.max(Message.sent_at).label("last_sent"),
                func.max(Message.opened_at).label("last_open"),
                func.count(Message.opened_at).label("opens"),
            )
            .join(Enrollment, Enrollment.id == Message.enrollment_id)
            .where(Message.channel == "email")
            .where(Message.status == "sent")
            .group_by(Enrollment.company_id)
        )
    ).all()
    for r in msg_rows:
        if r.company_id is None:
            continue
        existing = badges.get(r.company_id)
        if existing is None:
            badges[r.company_id] = CompanyCommsBadge(
                company_id=r.company_id,
                last_outbound_at=r.last_sent,
                last_open_at=r.last_open,
                sent_count=int(r.sent or 0),
                open_count=int(r.opens or 0),
            )
        else:
            existing.sent_count += int(r.sent or 0)
            existing.open_count += int(r.opens or 0)
            if r.last_sent and (existing.last_outbound_at is None or r.last_sent > existing.last_outbound_at):
                existing.last_outbound_at = r.last_sent
            if r.last_open and (existing.last_open_at is None or r.last_open > existing.last_open_at):
                existing.last_open_at = r.last_open

    return list(badges.values())


@router.get("/{company_id}/communications", response_model=CommunicationsResponse)
async def get_communications(
    company_id: UUID, auth: CurrentAuth, db: Db, limit: int = 200,
) -> CommunicationsResponse:
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="company not found")

    entries: list[CommunicationEntry] = []

    # ---- HaloPSA mail campaign recipients ----
    rcpt_rows = (
        await db.execute(
            select(MailCampaignRecipient, MailCampaign)
            .join(MailCampaign, MailCampaign.id == MailCampaignRecipient.campaign_id)
            .where(MailCampaignRecipient.company_id == company.id)
            .order_by(MailCampaignRecipient.sent_at.desc().nullslast())
            .limit(limit)
        )
    ).all()
    for r, c in rcpt_rows:
        entries.append(CommunicationEntry(
            id=f"campaign:{r.id}",
            kind="campaign_mail",
            subject=c.name,
            snippet=c.subject,
            to_name=r.name,
            to_email=r.email,
            sent_at=r.sent_at,
            delivered_at=r.delivered_at,
            opened_at=r.opened_at,
            clicked_at=r.clicked_at,
            bounced_at=r.bounced_at,
            status=r.status,
            campaign_id=str(c.id),
        ))

    # ---- Sequence emails (Message via Enrollment.company_id) ----
    msg_rows = (
        await db.execute(
            select(Message, Enrollment)
            .join(Enrollment, Enrollment.id == Message.enrollment_id)
            .where(Enrollment.company_id == company.id)
            .where(Message.channel == "email")
            .order_by(Message.sent_at.desc().nullslast())
            .limit(limit)
        )
    ).all()
    for m, _enr in msg_rows:
        entries.append(CommunicationEntry(
            id=f"seq:{m.id}",
            kind="sequence_mail",
            subject=m.subject,
            snippet=(m.body or "")[:160] if m.body else None,
            to_email=m.to_email,
            sent_at=m.sent_at,
            opened_at=m.opened_at,
            status=m.status,
        ))

    # ---- LinkedIn posts whose destination matches this company's LI URN ----
    # Best-effort: look at destinations[].target_urn vs a value stored on
    # the Company. Company model may not yet expose a linkedin_url; we
    # fall through silently when it doesn't.
    org_urn = getattr(company, "linkedin_url", None) or getattr(company, "linkedin_organization_urn", None)
    if org_urn and "urn:li:organization" in org_urn:
        posts = (
            await db.execute(
                select(SocialPost).where(SocialPost.status == "published")
                .order_by(SocialPost.published_at.desc().nullslast())
                .limit(limit)
            )
        ).scalars().all()
        for p in posts:
            for d in (p.destinations or []):
                if isinstance(d, dict) and d.get("target_urn") == org_urn:
                    # Find the post_url in publish_result
                    post_url = None
                    for r in (p.publish_result or []):
                        if isinstance(r, dict) and r.get("target_urn") == org_urn:
                            post_url = r.get("post_url")
                            break
                    entries.append(CommunicationEntry(
                        id=f"post:{p.id}",
                        kind="linkedin_post",
                        subject=p.title,
                        snippet=(p.body or "")[:160],
                        sent_at=p.published_at,
                        post_id=str(p.id),
                        external_url=post_url,
                        status=p.status,
                    ))
                    break

    # ---- LinkedIn outreach tasks ----
    tasks = (
        await db.execute(
            select(LinkedInTask).where(LinkedInTask.company_id == company.id)
            .order_by(LinkedInTask.scheduled_for.desc().nullslast())
            .limit(limit)
        )
    ).scalars().all()
    for t in tasks:
        entries.append(CommunicationEntry(
            id=f"task:{t.id}",
            kind="linkedin_task",
            subject=t.kind,
            snippet=t.suggested_text,
            sent_at=t.scheduled_for,
            status=t.status,
        ))

    # Sort newest-first across all kinds
    entries.sort(key=lambda e: e.sent_at or datetime(1970, 1, 1, tzinfo=None.__class__ or None), reverse=True)
    # The above sort needs tz; do it again safely with a fallback
    def _ts(e: CommunicationEntry) -> float:
        if e.sent_at is None:
            return 0.0
        return e.sent_at.timestamp()
    entries.sort(key=_ts, reverse=True)

    # Summary
    last_outbound = next((e.sent_at for e in entries if e.sent_at), None)
    last_open = next((e.opened_at for e in entries if e.opened_at), None)
    open_count = sum(1 for e in entries if e.opened_at)
    click_count = sum(1 for e in entries if e.clicked_at)

    return CommunicationsResponse(
        company_id=company.id,
        total=len(entries),
        entries=entries[:limit],
        last_outbound_at=last_outbound,
        last_open_at=last_open,
        open_count=open_count,
        click_count=click_count,
    )