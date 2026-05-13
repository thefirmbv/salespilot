"""Cron tick + webhook receivers.

Endpoints:
  POST /internal/autopilot/tick   — cron-driven scheduler. Guarded by
                                    X-Internal-Token == settings.autopilot_internal_token.
  POST /webhooks/mailgun          — Mailgun event webhook (delivered/opened/etc).
  POST /webhooks/mailgun-inbound  — Mailgun inbound reply route.
  GET  /oauth/linkedin/callback   — finishes LinkedIn OAuth and stores token.

All webhooks bypass JWT auth (they come from external services).
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Header, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from salespilot.config import get_settings
from salespilot.db import get_sessionmaker
from salespilot.deps import Db
from salespilot.integrations.autopilot_engine import (
    bucket_for_score,
    compute_next_action_at,
    render_template,
)
from salespilot.integrations.mailgun import (
    MailgunClient,
    MailgunCredentials,
    MailgunError,
    verify_webhook_signature,
)
from salespilot.models.autopilot import (
    Enrollment,
    LinkedInTask,
    MailSuppression,
    Message,
    Sequence,
    SequenceStep,
)
from salespilot.models.auth import Organization
from salespilot.models.crm import Company, Contact
from salespilot.models.integrations import Integration


internal_router = APIRouter(prefix="/internal", tags=["internal"])
webhooks_router = APIRouter(tags=["webhooks"])
oauth_router = APIRouter(prefix="/oauth", tags=["oauth"])


# ----------------------------------------------------------------------
# Helpers: run a SQL-level org context so RLS works inside the tick.
# ----------------------------------------------------------------------


async def _set_org_context(db: AsyncSession, org_id: UUID) -> None:
    await db.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))


async def _get_mailgun_for_org(db: AsyncSession, org_id: UUID) -> Integration | None:
    res = await db.execute(
        select(Integration).where(
            Integration.org_id == org_id, Integration.kind == "mailgun"
        )
    )
    return res.scalar_one_or_none()


def _mailgun_creds_from_row(row: Integration) -> MailgunCredentials:
    cfg = row.config_json or {}
    return MailgunCredentials(
        base_url=cfg.get("base_url") or "api.eu.mailgun.net",
        domain=cfg.get("domain", ""),
        api_key=cfg.get("api_key", ""),
        webhook_signing_key=cfg.get("webhook_signing_key"),
    )


# ----------------------------------------------------------------------
# Auto-enrol prospects matching a live sequence's bucket rule.
# ----------------------------------------------------------------------


async def _auto_enrol(db: AsyncSession, org_id: UUID) -> int:
    sequences = (
        await db.execute(
            select(Sequence).where(
                Sequence.status == "active",
                Sequence.auto_enroll_bucket.is_not(None),
            )
        )
    ).scalars().all()
    if not sequences:
        return 0

    candidates = (
        await db.execute(
            select(Company).where(
                Company.source == "salespilot",
                Company.lead_score >= 0,
            )
        )
    ).scalars().all()

    enrolled = 0
    for seq in sequences:
        bucket = seq.auto_enroll_bucket
        min_s = seq.auto_enroll_min_score
        max_s = seq.auto_enroll_max_score
        for c in candidates:
            if min_s is not None and (c.lead_score or 0) < min_s:
                continue
            if max_s is not None and (c.lead_score or 0) > max_s:
                continue
            if bucket and bucket_for_score(c.lead_score or 0) != bucket:
                continue
            existing = (
                await db.execute(
                    select(Enrollment).where(
                        Enrollment.sequence_id == seq.id,
                        Enrollment.company_id == c.id,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                continue
            now = datetime.now(UTC)
            db.add(
                Enrollment(
                    id=uuid4(),
                    org_id=org_id,
                    sequence_id=seq.id,
                    company_id=c.id,
                    contact_id=None,
                    status="active",
                    current_step_position=0,
                    score_at_enroll=c.lead_score,
                    bucket_at_enroll=bucket_for_score(c.lead_score or 0),
                    next_action_at=compute_next_action_at(
                        last_action_at=None,
                        wait_days=0,
                        window=seq.send_window_json or {},
                        cooldown_hours=seq.cooldown_hours,
                    ),
                    enrolled_at=now,
                )
            )
            enrolled += 1
    return enrolled


# ----------------------------------------------------------------------
# Execute one enrolment's next step.
# ----------------------------------------------------------------------


async def _process_enrollment(
    db: AsyncSession, enr: Enrollment, *, mg_row: Integration | None
) -> str:
    seq = await db.get(Sequence, enr.sequence_id)
    if seq is None or seq.status != "active":
        return "sequence-not-active"

    steps = (
        await db.execute(
            select(SequenceStep)
            .where(SequenceStep.sequence_id == seq.id)
            .order_by(SequenceStep.position.asc())
        )
    ).scalars().all()
    if not steps or enr.current_step_position >= len(steps):
        enr.status = "done"
        enr.next_action_at = None
        return "done"

    step = steps[enr.current_step_position]
    company = await db.get(Company, enr.company_id)
    contact = await db.get(Contact, enr.contact_id) if enr.contact_id else None
    if company is None:
        enr.status = "stopped"
        enr.stopped_reason = "company missing"
        enr.next_action_at = None
        return "company-missing"

    # Suppression check on the recipient e-mail.
    to_email = (contact.email if contact else None) or None
    if step.kind == "email":
        if not to_email:
            # Try the first contact for this company.
            first_contact = (
                await db.execute(
                    select(Contact).where(Contact.company_id == company.id).limit(1)
                )
            ).scalar_one_or_none()
            if first_contact and first_contact.email:
                to_email = first_contact.email
                enr.contact_id = first_contact.id
        if not to_email:
            # No deliverable address — skip this enrolment forward.
            enr.stopped_reason = "no contact email"
            enr.status = "stopped"
            enr.next_action_at = None
            return "no-email"

        # Check suppression.
        sup = (
            await db.execute(
                select(MailSuppression).where(MailSuppression.email == to_email)
            )
        ).scalar_one_or_none()
        if sup:
            enr.status = "stopped"
            enr.stopped_reason = f"suppressed ({sup.reason})"
            enr.next_action_at = None
            return "suppressed"

        if mg_row is None:
            # Don't kill the enrollment — just delay it. Once Mailgun is
            # configured, the next tick will pick it back up.
            enr.next_action_at = datetime.now(UTC) + timedelta(hours=1)
            return "waiting-for-mailgun"

        subject = render_template(step.template_subject or "", company=company, contact=contact)
        body = render_template(step.template_body or "", company=company, contact=contact)

        # Append unsubscribe footer (always — required for cold outreach).
        body += (
            "\n\n--\n"
            f"Reageer niet meer? Stuur 'STOP' terug en we halen je uit onze lijst.\n"
        )

        # Find previous message in the same enrolment for in-thread reply.
        prev_msg = None
        if step.reply_in_thread:
            prev_msg = (
                await db.execute(
                    select(Message)
                    .where(
                        Message.enrollment_id == enr.id,
                        Message.channel == "email",
                        Message.external_id.is_not(None),
                    )
                    .order_by(Message.sent_at.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()

        msg_row = Message(
            id=uuid4(),
            org_id=enr.org_id,
            enrollment_id=enr.id,
            step_id=step.id,
            channel="email",
            status="queued",
            subject=subject,
            body=body,
            to_email=to_email,
            from_email=seq.from_email,
            created_at=datetime.now(UTC),
        )
        db.add(msg_row)

        from_full = f'"{seq.from_name}" <{seq.from_email}>'
        try:
            async with MailgunClient(_mailgun_creds_from_row(mg_row)) as mg:
                resp = await mg.send(
                    from_full=from_full,
                    to=to_email,
                    subject=subject,
                    body_text=body,
                    reply_to=seq.reply_to_email,
                    in_reply_to=prev_msg.external_id if prev_msg else None,
                    references=prev_msg.external_id if prev_msg else None,
                    tags=["salespilot", f"seq:{seq.id}"],
                    custom_vars={
                        "enrollment_id": str(enr.id),
                        "message_id": str(msg_row.id),
                        "org_id": str(enr.org_id),
                    },
                )
            msg_id = (resp.get("id") or "").strip("<>")
            msg_row.external_id = msg_id
            msg_row.status = "sent"
            msg_row.sent_at = datetime.now(UTC)
            if prev_msg is not None and prev_msg.external_id:
                msg_row.thread_message_id = prev_msg.external_id
        except MailgunError as e:
            msg_row.status = "failed"
            msg_row.error = str(e)
            enr.last_action_at = datetime.now(UTC)
            # Retry the same step on next tick by NOT bumping position.
            enr.next_action_at = compute_next_action_at(
                last_action_at=datetime.now(UTC),
                wait_days=0,
                window=seq.send_window_json or {},
                cooldown_hours=max(1, seq.cooldown_hours // 24),
            )
            return f"mail-failed:{e}"

    elif step.kind in {"linkedin_connect", "linkedin_dm", "linkedin_like", "linkedin_visit"}:
        # We never auto-send LinkedIn actions. Spawn a task instead.
        suggested = render_template(step.template_body or "", company=company, contact=contact)
        db.add(
            LinkedInTask(
                id=uuid4(),
                org_id=enr.org_id,
                enrollment_id=enr.id,
                step_id=step.id,
                company_id=enr.company_id,
                contact_id=enr.contact_id,
                kind=step.kind,
                status="todo",
                suggested_text=suggested,
                scheduled_for=datetime.now(UTC),
            )
        )

    # Advance.
    now = datetime.now(UTC)
    enr.last_action_at = now
    enr.current_step_position += 1
    if enr.current_step_position >= len(steps):
        enr.status = "done"
        enr.next_action_at = None
    else:
        next_step = steps[enr.current_step_position]
        enr.next_action_at = compute_next_action_at(
            last_action_at=now,
            wait_days=next_step.wait_days,
            window=seq.send_window_json or {},
            cooldown_hours=seq.cooldown_hours,
        )
    return "advanced"


# ----------------------------------------------------------------------
# Scheduler tick — guarded by a static internal token.
# ----------------------------------------------------------------------


@internal_router.post("/autopilot/tick")
async def autopilot_tick(
    x_internal_token: str = Header(default=""),
) -> dict[str, Any]:
    settings = get_settings()
    expected = settings.autopilot_internal_token.get_secret_value()
    if not expected or x_internal_token != expected:
        raise HTTPException(status_code=401, detail="bad internal token")

    # We touch each org sequentially. Because we want RLS to behave we set
    # the app.current_org_id GUC per session.
    results: list[dict[str, Any]] = []
    async with get_sessionmaker()() as db:
        orgs = (await db.execute(select(Organization))).scalars().all()

    for org in orgs:
        async with get_sessionmaker()() as db:
            await _set_org_context(db, org.id)
            enrolled = await _auto_enrol(db, org.id)
            await db.flush()

            mg_row = await _get_mailgun_for_org(db, org.id)
            if mg_row is not None and not mg_row.is_enabled:
                mg_row = None

            now = datetime.now(UTC)
            due = (
                await db.execute(
                    select(Enrollment)
                    .where(
                        Enrollment.status == "active",
                        Enrollment.next_action_at.is_not(None),
                        Enrollment.next_action_at <= now,
                    )
                    .order_by(Enrollment.next_action_at.asc())
                    .limit(20)
                )
            ).scalars().all()

            actions: list[str] = []
            for e in due:
                code = await _process_enrollment(db, e, mg_row=mg_row)
                actions.append(f"{e.id}:{code}")
            await db.commit()
            results.append(
                {
                    "org_id": str(org.id),
                    "enrolled": enrolled,
                    "processed": len(due),
                    "actions": actions,
                }
            )
    return {"ok": True, "results": results}


# ----------------------------------------------------------------------
# Mailgun event webhook (delivered/opened/replied/bounced/unsubscribed)
# ----------------------------------------------------------------------


@webhooks_router.post("/webhooks/mailgun")
async def mailgun_event_webhook(request: Request) -> dict[str, Any]:
    """Mailgun POSTs JSON for opens/clicks/bounces.

    The payload's `event-data` block has a `message.headers.message-id`
    we can match back to our messages table.
    """
    payload = await request.json()
    sig = payload.get("signature") or {}
    timestamp = str(sig.get("timestamp", ""))
    token = sig.get("token", "")
    signature = sig.get("signature", "")
    event_data = payload.get("event-data") or {}
    event = event_data.get("event")
    message_id = (
        ((event_data.get("message") or {}).get("headers") or {}).get("message-id")
        or ""
    ).strip("<>")
    recipient = event_data.get("recipient") or ""

    async with get_sessionmaker()() as db:
        # Match message — we use external_id only (don't trust user_vars
        # blindly). Then derive org_id from the row.
        msg = None
        if message_id:
            msg = (
                await db.execute(select(Message).where(Message.external_id == message_id))
            ).scalar_one_or_none()
        if msg is None:
            return {"ok": False, "detail": "message not found"}

        # Verify signature if we have a signing key.
        sup_row = await db.execute(
            select(Integration).where(
                Integration.org_id == msg.org_id, Integration.kind == "mailgun"
            )
        )
        mg_int = sup_row.scalar_one_or_none()
        signing_key = (mg_int.config_json or {}).get("webhook_signing_key") if mg_int else None
        if signing_key and not verify_webhook_signature(
            signing_key, timestamp, token, signature
        ):
            raise HTTPException(status_code=400, detail="bad signature")

        await _set_org_context(db, msg.org_id)
        now = datetime.now(UTC)
        if event == "opened" and msg.opened_at is None:
            msg.opened_at = now
            if msg.status == "sent":
                msg.status = "opened"
        elif event in {"failed", "rejected", "bounced"}:
            msg.status = "bounced"
            if recipient:
                db.add(
                    MailSuppression(
                        id=uuid4(),
                        org_id=msg.org_id,
                        email=recipient,
                        reason="bounce",
                        source_message_id=msg.id,
                        created_at=now,
                    )
                )
        elif event in {"unsubscribed", "complained"}:
            msg.status = "unsubscribed"
            if recipient:
                db.add(
                    MailSuppression(
                        id=uuid4(),
                        org_id=msg.org_id,
                        email=recipient,
                        reason=event,
                        source_message_id=msg.id,
                        created_at=now,
                    )
                )
        await db.commit()
    return {"ok": True}


# ----------------------------------------------------------------------
# Mailgun inbound — reply detection.
# ----------------------------------------------------------------------


@webhooks_router.post("/webhooks/mailgun-inbound")
async def mailgun_inbound_webhook(request: Request) -> dict[str, Any]:
    """Mailgun route forwards inbound mail here as multipart form-data.

    We read In-Reply-To / References to match back to an outgoing message,
    then mark the enrolment as 'replied'.
    """
    form = await request.form()
    in_reply_to = (form.get("In-Reply-To") or "").strip("<>")
    references = form.get("References") or ""
    sender = form.get("sender") or form.get("from") or ""
    body = form.get("stripped-text") or form.get("body-plain") or ""
    timestamp = str(form.get("timestamp", ""))
    token = str(form.get("token", ""))
    signature = str(form.get("signature", ""))

    # Try direct match first, then any id in References.
    candidates = []
    if in_reply_to:
        candidates.append(in_reply_to)
    for ref in references.split():
        candidates.append(ref.strip("<>"))

    async with get_sessionmaker()() as db:
        msg = None
        for cid in candidates:
            if not cid:
                continue
            res = await db.execute(select(Message).where(Message.external_id == cid))
            msg = res.scalar_one_or_none()
            if msg:
                break
        if msg is None:
            return {"ok": False, "detail": "no matching outgoing message"}

        sup_row = await db.execute(
            select(Integration).where(
                Integration.org_id == msg.org_id, Integration.kind == "mailgun"
            )
        )
        mg_int = sup_row.scalar_one_or_none()
        signing_key = (mg_int.config_json or {}).get("webhook_signing_key") if mg_int else None
        if signing_key and not verify_webhook_signature(
            signing_key, timestamp, token, signature
        ):
            raise HTTPException(status_code=400, detail="bad signature")

        await _set_org_context(db, msg.org_id)
        now = datetime.now(UTC)
        msg.replied_at = now
        msg.status = "replied"

        # Stop the enrolment if the sequence wants stop_on_reply.
        enr = await db.get(Enrollment, msg.enrollment_id)
        if enr is not None and enr.status == "active":
            seq = await db.get(Sequence, enr.sequence_id)
            if seq is None or seq.stop_on_reply:
                enr.status = "replied"
                enr.stopped_at = now
                enr.stopped_reason = "reply"
                enr.next_action_at = None

        # Auto-suppress STOP-replies.
        if body and "stop" in body.lower()[:80]:
            db.add(
                MailSuppression(
                    id=uuid4(),
                    org_id=msg.org_id,
                    email=(sender or msg.to_email or ""),
                    reason="unsubscribe",
                    source_message_id=msg.id,
                    created_at=now,
                )
            )
        await db.commit()
    return {"ok": True, "matched_message": str(msg.id)}


# ----------------------------------------------------------------------
# LinkedIn OAuth callback.
# ----------------------------------------------------------------------


@oauth_router.get("/linkedin/callback")
async def linkedin_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
):
    """LinkedIn redirects here with ?code=...&state=<org_id>."""
    import httpx
    from sqlalchemy import select

    settings = get_settings()
    public_base = settings.public_base_url
    redirect_uri = f"{public_base}/api/v1/oauth/linkedin/callback"

    try:
        org_id = UUID(state)
    except ValueError:
        raise HTTPException(status_code=400, detail="bad state")

    async with get_sessionmaker()() as db:
        await _set_org_context(db, org_id)
        row = (
            await db.execute(
                select(Integration).where(
                    Integration.org_id == org_id, Integration.kind == "linkedin"
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=400, detail="LinkedIn integration not configured")
        cfg = row.config_json or {}
        client_id = cfg.get("client_id")
        client_secret = cfg.get("client_secret")
        if not client_id or not client_secret:
            raise HTTPException(status_code=400, detail="LinkedIn client_id/secret missing")

        # Exchange code for access token.
        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.post(
                "https://www.linkedin.com/oauth/v2/accessToken",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if res.status_code >= 400:
            raise HTTPException(
                status_code=502, detail=f"LinkedIn token exchange failed: {res.text[:300]}"
            )
        body = res.json()
        access_token = body.get("access_token")
        expires_in = body.get("expires_in")
        # Read /v2/userinfo for the URN.
        async with httpx.AsyncClient(timeout=20.0) as client:
            ures = await client.get(
                "https://api.linkedin.com/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        person_urn = None
        if ures.status_code == 200:
            sub = ures.json().get("sub")
            if sub:
                person_urn = f"urn:li:person:{sub}"

        cfg["access_token"] = access_token
        cfg["expires_at"] = (
            datetime.now(UTC) + timedelta(seconds=int(expires_in or 0))
        ).isoformat() if expires_in else None
        if person_urn:
            cfg["person_urn"] = person_urn
        row.config_json = cfg
        row.is_enabled = True
        await db.commit()

    return RedirectResponse(url=f"{public_base}/settings/integrations/linkedin?ok=1")


@internal_router.post("/social/tick")
async def social_tick(
    x_internal_token: str = Header(default=""),
) -> dict[str, Any]:
    """Run the social-scheduler for every org. Authenticated with the
    same internal token as the autopilot tick.

    This calls api.social._publish_one for each due scheduled post,
    iterating per org so RLS context is correct.
    """
    settings = get_settings()
    expected = settings.autopilot_internal_token.get_secret_value()
    if not expected or x_internal_token != expected:
        raise HTTPException(status_code=401, detail="bad internal token")

    from salespilot.api.social import _publish_one
    from salespilot.models.social import SocialPost

    total_due = 0
    total_published = 0
    total_failed = 0

    async with get_sessionmaker()() as db:
        orgs = (await db.execute(select(Organization))).scalars().all()

    for org in orgs:
        async with get_sessionmaker()() as db:
            await _set_org_context(db, org.id)
            now = datetime.now(UTC)
            due = (
                await db.execute(
                    select(SocialPost).where(
                        SocialPost.status == "scheduled",
                        SocialPost.scheduled_at.is_not(None),
                        SocialPost.scheduled_at <= now,
                    )
                )
            ).scalars().all()
            for p in due:
                total_due += 1
                p.status = "publishing"
                await db.flush()
                try:
                    await _publish_one(db, p)
                    if p.status == "published":
                        total_published += 1
                    else:
                        total_failed += 1
                except Exception as e:  # noqa: BLE001
                    p.status = "failed"
                    p.last_error = str(e)[:500]
                    p.retry_count += 1
                    await db.flush()
                    total_failed += 1
            await db.commit()

    return {
        "ok": True,
        "due": total_due,
        "published": total_published,
        "failed": total_failed,
    }

