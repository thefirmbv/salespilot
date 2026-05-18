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
)
from salespilot.integrations.mail_throttle import check_send_quota
from salespilot.integrations.mailgun import (
    MailgunCredentials,
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

        # Sender-reputation throttle. Conservative on a new subdomain;
        # configurable via integrations.config_json.limits.
        allowed, retry_after, reason = await check_send_quota(
            db, org_id=enr.org_id, integ=mg_row
        )
        if not allowed:
            msg_row.status = "throttled"
            msg_row.error = f"rate-limit: {reason}"
            enr.last_action_at = datetime.now(UTC)
            enr.next_action_at = datetime.now(UTC) + timedelta(seconds=retry_after)
            return f"throttled:{reason}"

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


@internal_router.post("/wespennest/tick")
async def wespennest_tick(
    x_internal_token: str = Header(default=""),
) -> dict[str, Any]:
    """Run periodic Wespennest scanners for every org.

    Default schedule (cron-side):
      - this endpoint is hit once every 4 hours
      - it runs overname_monitor + m365_scanner + msp_fingerprint
        + kvk_geofilter + decision_maker_finder in sequence per org
    """
    settings = get_settings()
    expected = settings.autopilot_internal_token.get_secret_value()
    if not expected or x_internal_token != expected:
        raise HTTPException(status_code=401, detail="bad internal token")

    from salespilot.integrations.wespennest_pipeline import run_pipeline_job

    results: list[dict[str, Any]] = []
    async with get_sessionmaker()() as db:
        orgs = (await db.execute(select(Organization))).scalars().all()

    for org in orgs:
        async with get_sessionmaker()() as db:
            await _set_org_context(db, org.id)
            for kind in (
                "overname_monitor",
                "m365_scanner",
                "msp_fingerprint",
                "kvk_geofilter",
                "decision_maker_finder",
            ):
                try:
                    run = await run_pipeline_job(db, org_id=org.id, job_kind=kind)
                    results.append({
                        "org": str(org.id), "kind": kind,
                        "status": run.status,
                        "processed": run.items_processed,
                        "created": run.items_created,
                    })
                except Exception as e:  # noqa: BLE001
                    results.append({
                        "org": str(org.id), "kind": kind,
                        "status": "failed", "error": str(e)[:200],
                    })
            await db.commit()

    return {"ok": True, "runs": len(results), "results": results}


@internal_router.post("/social/metrics-refresh")
async def social_metrics_refresh(
    x_internal_token: str = Header(default=""),
) -> dict[str, Any]:
    """Daily-ish: walk every published social post from the last 30 days
    and pull a fresh metric snapshot from LinkedIn.

    Authenticated with the same internal token as the autopilot tick.
    """
    settings = get_settings()
    expected = settings.autopilot_internal_token.get_secret_value()
    if not expected or x_internal_token != expected:
        raise HTTPException(status_code=401, detail="bad internal token")

    from datetime import timedelta
    from uuid import uuid4
    from salespilot.api.social import _get_linkedin_token
    from salespilot.integrations.linkedin import LinkedInClient
    from salespilot.models.social import SocialPost, SocialPostMetrics

    refreshed = 0
    failed = 0
    skipped = 0
    cutoff = datetime.now(UTC) - timedelta(days=30)

    async with get_sessionmaker()() as db:
        orgs = (await db.execute(select(Organization))).scalars().all()

    for org in orgs:
        async with get_sessionmaker()() as db:
            await _set_org_context(db, org.id)
            posts = (
                await db.execute(
                    select(SocialPost).where(
                        SocialPost.status == "published",
                        SocialPost.published_at.is_not(None),
                        SocialPost.published_at >= cutoff,
                    )
                )
            ).scalars().all()
            if not posts:
                continue
            try:
                token = await _get_linkedin_token(db)
            except Exception:
                # LinkedIn not configured for this org -- skip silently
                skipped += len(posts)
                continue

            now = datetime.now(UTC)
            async with LinkedInClient(token) as li:
                for p in posts:
                    for entry in (p.publish_result or []):
                        if not isinstance(entry, dict):
                            continue
                        ppid = entry.get("platform_post_id")
                        if not ppid:
                            continue
                        try:
                            stats = await li.get_post_stats(ppid)
                        except Exception:  # noqa: BLE001
                            failed += 1
                            continue
                        db.add(SocialPostMetrics(
                            id=uuid4(),
                            org_id=org.id,
                            post_id=p.id,
                            platform_post_id=ppid,
                            snapshot_at=now,
                            impressions=int(stats.get("impressions") or 0),
                            likes=int(stats.get("likes") or 0),
                            comments=int(stats.get("comments") or 0),
                            shares=int(stats.get("shares") or 0),
                            clicks=int(stats.get("clicks") or 0),
                            raw=stats,
                        ))
                        refreshed += 1
            await db.commit()

    return {
        "ok": True,
        "refreshed": refreshed,
        "failed": failed,
        "skipped": skipped,
    }



@internal_router.post("/unifi/tick")
async def unifi_tick(
    x_internal_token: str = Header(default=""),
) -> dict[str, Any]:
    """Poll UniFi Site Manager for every org with the integration enabled.

    Schedule (cron-side): every 2 minutes by default. Each org's
    integration row has a poll_interval_seconds field; we honor it by
    skipping orgs whose last_sync_at is more recent than that.
    """
    settings = get_settings()
    expected = settings.autopilot_internal_token.get_secret_value()
    if not expected or x_internal_token != expected:
        raise HTTPException(status_code=401, detail="bad internal token")

    from salespilot.integrations.unifi import UniFiClient, UniFiCredentials, UniFiError
    from salespilot.integrations.unifi_poller import poll_unifi_for_org

    polled_at = datetime.now(UTC)
    results: list[dict[str, Any]] = []

    async with get_sessionmaker()() as db:
        orgs = (await db.execute(select(Organization))).scalars().all()

    for org in orgs:
        async with get_sessionmaker()() as db:
            await _set_org_context(db, org.id)
            row = (
                await db.execute(
                    select(Integration).where(
                        Integration.org_id == org.id,
                        Integration.kind == "unifi",
                    )
                )
            ).scalar_one_or_none()
            if row is None or not row.is_enabled:
                continue
            cfg = row.config_json or {}
            api_key = cfg.get("api_key")
            if not api_key:
                continue
            # Honor per-org poll interval
            interval = int(cfg.get("poll_interval_seconds") or 120)
            if row.last_sync_at and (polled_at - row.last_sync_at).total_seconds() < interval - 5:
                continue
            try:
                creds = UniFiCredentials(
                    api_key=api_key,
                    base_url=cfg.get("base_url") or "https://api.ui.com",
                )
                async with UniFiClient(creds) as client:
                    counters = await poll_unifi_for_org(db, org_id=org.id, client=client)
                row.last_sync_at = polled_at
                row.last_sync_status = "ok"
                row.last_sync_message = (
                    f"{counters['hosts_seen']} hosts, "
                    f"{counters['devices_seen']} devices, "
                    f"{counters['state_events']} state-changes"
                )
                results.append({"org": str(org.id), "ok": True, **counters})
            except UniFiError as e:
                row.last_sync_status = "error"
                row.last_sync_message = str(e)[:500]
                row.last_sync_at = polled_at
                results.append({"org": str(org.id), "ok": False, "error": str(e)[:200]})
            await db.commit()

    return {"ok": True, "polled": len(results), "results": results}


# ----------------------------------------------------------------------
# Plesk poller tick (cron: */5 * * * *)
# ----------------------------------------------------------------------


@internal_router.post("/plesk/tick")
async def plesk_tick(
    x_internal_token: str = Header(default=""),
) -> dict[str, Any]:
    """Poll alle Plesk-servers voor elke org met integratie ingeschakeld.

    Default schedule: elke 5 minuten. Honors per-org poll_interval.
    Looped through plesk_servers tabel; faalt 1 server, andere gaan door.
    """
    settings = get_settings()
    expected = settings.autopilot_internal_token.get_secret_value()
    if not expected or x_internal_token != expected:
        raise HTTPException(status_code=401, detail="bad internal token")

    from salespilot.integrations.plesk import (
        PleskClient, PleskCredentials, PleskError,
    )
    from salespilot.integrations.plesk_poller import poll_plesk_for_org
    from salespilot.models.hosting import PleskServer

    polled_at = datetime.now(UTC)
    results: list[dict[str, Any]] = []

    async with get_sessionmaker()() as db:
        orgs = (await db.execute(select(Organization))).scalars().all()

    for org in orgs:
        async with get_sessionmaker()() as db:
            await _set_org_context(db, org.id)
            row = (await db.execute(
                select(Integration).where(
                    Integration.org_id == org.id,
                    Integration.kind == "plesk",
                )
            )).scalar_one_or_none()
            if row is None or not row.is_enabled:
                continue
            cfg = row.config_json or {}
            interval = int(cfg.get("poll_interval_seconds") or 300)
            if row.last_sync_at and (polled_at - row.last_sync_at).total_seconds() < interval - 5:
                continue

            servers = (await db.execute(
                select(PleskServer).where(PleskServer.is_enabled.is_(True))
            )).scalars().all()
            if not servers:
                continue

            org_subs = 0
            org_errors = 0
            for s in servers:
                if not s.api_key:
                    continue
                try:
                    creds = PleskCredentials(
                        api_key=s.api_key, base_url=s.base_url,
                        verify_tls=s.verify_tls,
                    )
                    async with PleskClient(creds) as client:
                        counters = await poll_plesk_for_org(
                            db, org_id=org.id, client=client, server_id=s.id,
                        )
                    org_subs += counters["subscriptions_seen"]
                    s.last_sync_at = polled_at
                    s.last_sync_status = "ok"
                    s.last_sync_message = (
                        f"{counters['subscriptions_seen']} subs, "
                        f"{counters['domains_seen']} domains"
                    )
                except PleskError as e:
                    org_errors += 1
                    s.last_sync_at = polled_at
                    s.last_sync_status = "error"
                    s.last_sync_message = str(e)[:500]

            row.last_sync_at = polled_at
            row.last_sync_status = "ok" if org_errors == 0 else ("partial" if org_subs > 0 else "error")
            row.last_sync_message = f"{len(servers)} servers, {org_subs} subscriptions"
            await db.commit()

            results.append({
                "org": str(org.id), "servers": len(servers),
                "subscriptions": org_subs, "errors": org_errors,
            })

    return {"ok": True, "orgs_polled": len(results), "results": results}


# ----------------------------------------------------------------------
# Openprovider poller tick (cron: 0 */1 * * *)
# ----------------------------------------------------------------------


@internal_router.post("/openprovider/tick")
async def openprovider_tick(
    x_internal_token: str = Header(default=""),
) -> dict[str, Any]:
    """Poll Openprovider domeinen voor elke org met integratie aan.
    Default schedule: elk uur (domeinen wijzigen niet vaak)."""
    settings = get_settings()
    expected = settings.autopilot_internal_token.get_secret_value()
    if not expected or x_internal_token != expected:
        raise HTTPException(status_code=401, detail="bad internal token")

    from salespilot.integrations.openprovider import (
        OpenproviderClient, OpenproviderCredentials, OpenproviderError,
    )
    from salespilot.integrations.openprovider_poller import (
        poll_openprovider_for_org,
    )

    polled_at = datetime.now(UTC)
    results: list[dict[str, Any]] = []

    async with get_sessionmaker()() as db:
        orgs = (await db.execute(select(Organization))).scalars().all()

    for org in orgs:
        async with get_sessionmaker()() as db:
            await _set_org_context(db, org.id)
            row = (await db.execute(
                select(Integration).where(
                    Integration.org_id == org.id,
                    Integration.kind == "openprovider",
                )
            )).scalar_one_or_none()
            if row is None or not row.is_enabled:
                continue
            cfg = row.config_json or {}
            if not cfg.get("username") or not cfg.get("password"):
                continue
            interval = int(cfg.get("poll_interval_seconds") or 3600)
            if row.last_sync_at and (polled_at - row.last_sync_at).total_seconds() < interval - 30:
                continue

            try:
                creds = OpenproviderCredentials(
                    username=cfg["username"], password=cfg["password"],
                    base_url=cfg.get("base_url") or "https://api.openprovider.eu",
                    bound_ip=cfg.get("bound_ip"),
                )
                async with OpenproviderClient(creds) as client:
                    counters = await poll_openprovider_for_org(
                        db, org_id=org.id, client=client,
                    )
                row.last_sync_at = polled_at
                row.last_sync_status = "ok"
                row.last_sync_message = f"{counters['domains_seen']} domains ({counters['domains_new']} nieuw)"
                results.append({"org": str(org.id), "domains": counters["domains_seen"]})
            except OpenproviderError as e:
                row.last_sync_at = polled_at
                row.last_sync_status = "error"
                row.last_sync_message = str(e)[:500]
                results.append({"org": str(org.id), "error": str(e)[:100]})
            await db.commit()

    return {"ok": True, "orgs_polled": len(results), "results": results}


# ----------------------------------------------------------------------
# NMBRS cron tick — uurlijkse sync van medewerkers (auto-discover nieuwe)
# ----------------------------------------------------------------------


@internal_router.post("/nmbrs/tick")
async def nmbrs_tick(
    x_internal_token: str = Header(default=""),
) -> dict[str, Any]:
    """Sync NMBRS-medewerkers per org. Pickt nieuwe medewerkers
    automatisch op (upsert by nmbrs_employee_id).

    Skip-condities:
      - geen NMBRS-integration voor de org
      - integration is_enabled=false
      - geen refresh_token (user heeft consent niet gegeven)
    """
    from salespilot.integrations.nmbrs import NmbrsClient, NmbrsAuthError, NmbrsConfigError
    from salespilot.models.inventory import Employee

    settings = get_settings()
    expected = settings.autopilot_internal_token.get_secret_value()
    if not expected or x_internal_token != expected:
        raise HTTPException(status_code=401, detail="bad internal token")

    results: list[dict[str, Any]] = []

    async with get_sessionmaker()() as db:
        orgs = (await db.execute(select(Organization))).scalars().all()

    for org in orgs:
        async with get_sessionmaker()() as db:
            await _set_org_context(db, org.id)

            integ = (
                await db.execute(
                    select(Integration).where(
                        Integration.org_id == org.id,
                        Integration.kind == "nmbrs",
                    )
                )
            ).scalar_one_or_none()
            if integ is None or not integ.is_enabled:
                continue
            cfg = integ.config_json or {}
            if not cfg.get("refresh_token"):
                continue  # user heeft nog geen consent gegeven

            client = NmbrsClient(integ, db)
            created = updated = unchanged = skipped = 0

            try:
                companies = await client.companies()
            except (NmbrsAuthError, NmbrsConfigError) as e:
                integ.last_sync_at = datetime.now(UTC)
                integ.last_sync_status = "error"
                integ.last_sync_message = f"companies fetch failed: {str(e)[:160]}"
                await db.flush()
                results.append({"org": str(org.id), "error": str(e)[:120]})
                continue

            for company in companies:
                cid = str(company.get("id") or company.get("companyId") or "")
                if not cid:
                    continue
                try:
                    employees_raw = await client.employees(cid)
                except Exception:
                    continue
                for emp in employees_raw:
                    nmbrs_emp_id = str(emp.get("id") or emp.get("employeeId") or "")
                    if not nmbrs_emp_id:
                        continue
                    try:
                        pi = await client.employee_personal_info(nmbrs_emp_id)
                    except Exception:
                        continue
                    first = (pi.get("firstName") or "").strip()
                    last = (pi.get("lastName") or "").strip()
                    prefix = (pi.get("prefix") or "").strip()
                    full = " ".join(p for p in [first, prefix, last] if p) or (
                        emp.get("displayName") or ""
                    )
                    email = (
                        pi.get("emailWork") or pi.get("emailPrivate")
                        or emp.get("email") or ""
                    ).strip().lower() or None

                    if not full:
                        skipped += 1
                        continue

                    existing = (
                        await db.execute(
                            select(Employee).where(
                                Employee.nmbrs_employee_id == nmbrs_emp_id
                            )
                        )
                    ).scalar_one_or_none()

                    now = datetime.now(UTC)
                    if existing:
                        changed = False
                        if existing.full_name != full:
                            existing.full_name = full; changed = True
                        if email and existing.email != email:
                            existing.email = email; changed = True
                        if existing.nmbrs_company_id != cid:
                            existing.nmbrs_company_id = cid; changed = True
                        if changed:
                            existing.updated_at = now
                            updated += 1
                        else:
                            unchanged += 1
                    else:
                        db.add(Employee(
                            id=uuid4(), org_id=org.id,
                            full_name=full, email=email, status="active",
                            nmbrs_employee_id=nmbrs_emp_id,
                            nmbrs_company_id=cid,
                            created_at=now, updated_at=now,
                        ))
                        created += 1

            integ.last_sync_at = datetime.now(UTC)
            integ.last_sync_status = "ok"
            integ.last_sync_message = (
                f"cron sync: {created} new, {updated} updated, "
                f"{unchanged} unchanged, {skipped} skipped"
            )
            await db.flush()
            results.append({
                "org": str(org.id),
                "created": created, "updated": updated,
                "unchanged": unchanged, "skipped": skipped,
            })

    return {"ok": True, "orgs_synced": len(results), "results": results}
