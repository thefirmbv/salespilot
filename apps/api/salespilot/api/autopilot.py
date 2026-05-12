"""Sequences, enrollments, messages, LinkedIn tasks, posts.

Plus the autopilot scheduler endpoint POST /internal/autopilot/tick guarded
by a static internal token (so a cron can call it).

The scheduler is intentionally simple: at each tick we
  (a) auto-enrol prospects matching live sequences' bucket rules,
  (b) take a small batch of due enrollments and run their next step,
  (c) bump status / next_action_at accordingly.

Mail sends happen synchronously inside the tick. That's fine at this
volume; if we ever scale up we can swap in rq/celery.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import and_, func, or_, select

from salespilot.config import get_settings
from salespilot.deps import CurrentAuth, Db
from salespilot.integrations.autopilot_engine import (
    bucket_for_score,
    compute_next_action_at,
    render_template,
)
from salespilot.integrations.mailgun import (
    MailgunClient,
    MailgunCredentials,
    MailgunError,
)
from salespilot.models.autopilot import (
    Enrollment,
    LinkedInPost,
    LinkedInTask,
    MailSuppression,
    Message,
    Sequence,
    SequenceStep,
)
from salespilot.models.auth import Organization
from salespilot.models.crm import Company, Contact
from salespilot.models.integrations import Integration
from salespilot.schemas.autopilot import (
    EnrollmentCreate,
    EnrollmentPublic,
    LinkedInPostCreate,
    LinkedInPostPublic,
    LinkedInPostUpdate,
    LinkedInTaskCreate,
    LinkedInTaskPublic,
    LinkedInTaskUpdate,
    MessagePublic,
    SequenceCreate,
    SequencePublic,
    SequenceStats,
    SequenceStepCreate,
    SequenceStepPublic,
    SequenceStepUpdate,
    SequenceUpdate,
)

router = APIRouter(tags=["autopilot"])


# ---------- Sequences ----------


@router.get("/sequences", response_model=list[SequencePublic])
async def list_sequences(auth: CurrentAuth, db: Db) -> list[SequencePublic]:
    rows = (await db.execute(select(Sequence).order_by(Sequence.created_at.desc()))).scalars().all()

    # Counts per sequence — keep it cheap: one aggregate query.
    enrollments = (await db.execute(select(Enrollment))).scalars().all()
    by_seq: dict[UUID, dict[str, int]] = {}
    for e in enrollments:
        bucket = by_seq.setdefault(e.sequence_id, {"active": 0, "replied": 0})
        if e.status == "active":
            bucket["active"] += 1
        elif e.status == "replied":
            bucket["replied"] += 1

    out: list[SequencePublic] = []
    for r in rows:
        pub = SequencePublic.model_validate(r)
        counts = by_seq.get(r.id, {})
        pub.enrollments_active = counts.get("active", 0)
        pub.enrollments_replied = counts.get("replied", 0)
        out.append(pub)
    return out


@router.post("/sequences", response_model=SequencePublic)
async def create_sequence(data: SequenceCreate, auth: CurrentAuth, db: Db) -> SequencePublic:
    obj = Sequence(
        id=uuid4(),
        org_id=auth.org_id,
        name=data.name,
        description=data.description,
        status=data.status,
        auto_enroll_bucket=data.auto_enroll_bucket,
        auto_enroll_min_score=data.auto_enroll_min_score,
        auto_enroll_max_score=data.auto_enroll_max_score,
        from_name=data.from_name,
        from_email=data.from_email,
        reply_to_email=data.reply_to_email,
        daily_limit=data.daily_limit,
        send_window_json=data.send_window_json.model_dump(),
        cooldown_hours=data.cooldown_hours,
        stop_on_reply=data.stop_on_reply,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return SequencePublic.model_validate(obj)


@router.get("/sequences/{seq_id}", response_model=SequencePublic)
async def get_sequence(seq_id: UUID, auth: CurrentAuth, db: Db) -> SequencePublic:
    obj = await db.get(Sequence, seq_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    return SequencePublic.model_validate(obj)


@router.patch("/sequences/{seq_id}", response_model=SequencePublic)
async def update_sequence(
    seq_id: UUID, data: SequenceUpdate, auth: CurrentAuth, db: Db
) -> SequencePublic:
    obj = await db.get(Sequence, seq_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    payload = data.model_dump(exclude_unset=True)
    if "send_window_json" in payload and payload["send_window_json"] is not None:
        payload["send_window_json"] = data.send_window_json.model_dump() if data.send_window_json else None
    for k, v in payload.items():
        setattr(obj, k, v)
    await db.flush()
    await db.refresh(obj)
    return SequencePublic.model_validate(obj)


@router.delete("/sequences/{seq_id}")
async def delete_sequence(seq_id: UUID, auth: CurrentAuth, db: Db) -> dict[str, bool]:
    obj = await db.get(Sequence, seq_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    await db.delete(obj)
    await db.flush()
    return {"ok": True}


# ---------- Sequence steps ----------


@router.get("/sequences/{seq_id}/steps", response_model=list[SequenceStepPublic])
async def list_steps(seq_id: UUID, auth: CurrentAuth, db: Db) -> list[SequenceStepPublic]:
    rows = (
        await db.execute(
            select(SequenceStep)
            .where(SequenceStep.sequence_id == seq_id)
            .order_by(SequenceStep.position.asc())
        )
    ).scalars().all()
    return [SequenceStepPublic.model_validate(r) for r in rows]


@router.post("/sequences/{seq_id}/steps", response_model=SequenceStepPublic)
async def create_step(
    seq_id: UUID, data: SequenceStepCreate, auth: CurrentAuth, db: Db
) -> SequenceStepPublic:
    seq = await db.get(Sequence, seq_id)
    if seq is None:
        raise HTTPException(status_code=404, detail="sequence not found")
    obj = SequenceStep(
        id=uuid4(),
        org_id=auth.org_id,
        sequence_id=seq_id,
        position=data.position,
        kind=data.kind,
        wait_days=data.wait_days,
        template_subject=data.template_subject,
        template_body=data.template_body,
        reply_in_thread=data.reply_in_thread,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return SequenceStepPublic.model_validate(obj)


@router.patch("/sequences/{seq_id}/steps/{step_id}", response_model=SequenceStepPublic)
async def update_step(
    seq_id: UUID,
    step_id: UUID,
    data: SequenceStepUpdate,
    auth: CurrentAuth,
    db: Db,
) -> SequenceStepPublic:
    obj = await db.get(SequenceStep, step_id)
    if obj is None or obj.sequence_id != seq_id:
        raise HTTPException(status_code=404, detail="not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    await db.refresh(obj)
    return SequenceStepPublic.model_validate(obj)


@router.delete("/sequences/{seq_id}/steps/{step_id}")
async def delete_step(
    seq_id: UUID, step_id: UUID, auth: CurrentAuth, db: Db
) -> dict[str, bool]:
    obj = await db.get(SequenceStep, step_id)
    if obj is None or obj.sequence_id != seq_id:
        raise HTTPException(status_code=404, detail="not found")
    await db.delete(obj)
    await db.flush()
    return {"ok": True}


# ---------- Enrollments ----------


@router.get("/enrollments", response_model=list[EnrollmentPublic])
async def list_enrollments(auth: CurrentAuth, db: Db) -> list[EnrollmentPublic]:
    rows = (
        await db.execute(select(Enrollment).order_by(Enrollment.created_at.desc()))
    ).scalars().all()
    return [EnrollmentPublic.model_validate(r) for r in rows]


@router.post("/enrollments", response_model=EnrollmentPublic)
async def create_enrollment(
    data: EnrollmentCreate, auth: CurrentAuth, db: Db
) -> EnrollmentPublic:
    company = await db.get(Company, data.company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="company not found")
    seq = await db.get(Sequence, data.sequence_id)
    if seq is None:
        raise HTTPException(status_code=404, detail="sequence not found")
    # Reject duplicates.
    existing = (
        await db.execute(
            select(Enrollment).where(
                Enrollment.sequence_id == data.sequence_id,
                Enrollment.company_id == data.company_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="already enrolled")
    now = datetime.now(UTC)
    obj = Enrollment(
        id=uuid4(),
        org_id=auth.org_id,
        sequence_id=data.sequence_id,
        company_id=data.company_id,
        contact_id=data.contact_id,
        status="active",
        current_step_position=0,
        score_at_enroll=company.lead_score,
        bucket_at_enroll=bucket_for_score(company.lead_score or 0),
        next_action_at=compute_next_action_at(
            last_action_at=None,
            wait_days=0,
            window=seq.send_window_json or {},
            cooldown_hours=seq.cooldown_hours,
        ),
        enrolled_at=now,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return EnrollmentPublic.model_validate(obj)


@router.post("/enrollments/{enr_id}/stop", response_model=EnrollmentPublic)
async def stop_enrollment(
    enr_id: UUID, auth: CurrentAuth, db: Db
) -> EnrollmentPublic:
    obj = await db.get(Enrollment, enr_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    obj.status = "stopped"
    obj.stopped_at = datetime.now(UTC)
    obj.stopped_reason = "manual"
    obj.next_action_at = None
    await db.flush()
    await db.refresh(obj)
    return EnrollmentPublic.model_validate(obj)


# ---------- Messages (read-only listing) ----------


@router.get("/messages", response_model=list[MessagePublic])
async def list_messages(
    auth: CurrentAuth,
    db: Db,
    enrollment_id: UUID | None = None,
    company_id: UUID | None = None,
    limit: int = 100,
) -> list[MessagePublic]:
    stmt = select(Message).order_by(Message.created_at.desc()).limit(limit)
    if enrollment_id:
        stmt = stmt.where(Message.enrollment_id == enrollment_id)
    if company_id:
        stmt = (
            stmt.join(Enrollment, Enrollment.id == Message.enrollment_id)
            .where(Enrollment.company_id == company_id)
        )
    rows = (await db.execute(stmt)).scalars().all()
    return [MessagePublic.model_validate(r) for r in rows]


# ---------- LinkedIn tasks ----------


@router.get("/linkedin_tasks", response_model=list[LinkedInTaskPublic])
async def list_linkedin_tasks(
    auth: CurrentAuth,
    db: Db,
    status: str | None = None,
    company_id: UUID | None = None,
) -> list[LinkedInTaskPublic]:
    stmt = select(LinkedInTask).order_by(LinkedInTask.created_at.desc())
    if status:
        stmt = stmt.where(LinkedInTask.status == status)
    if company_id:
        stmt = stmt.where(LinkedInTask.company_id == company_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [LinkedInTaskPublic.model_validate(r) for r in rows]


@router.post("/linkedin_tasks", response_model=LinkedInTaskPublic)
async def create_linkedin_task(
    data: LinkedInTaskCreate, auth: CurrentAuth, db: Db
) -> LinkedInTaskPublic:
    obj = LinkedInTask(
        id=uuid4(),
        org_id=auth.org_id,
        company_id=data.company_id,
        contact_id=data.contact_id,
        kind=data.kind,
        status="todo",
        suggested_text=data.suggested_text,
        profile_url=data.profile_url,
        post_url=data.post_url,
        scheduled_for=data.scheduled_for,
        notes=data.notes,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return LinkedInTaskPublic.model_validate(obj)


@router.patch("/linkedin_tasks/{task_id}", response_model=LinkedInTaskPublic)
async def update_linkedin_task(
    task_id: UUID, data: LinkedInTaskUpdate, auth: CurrentAuth, db: Db
) -> LinkedInTaskPublic:
    obj = await db.get(LinkedInTask, task_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    payload = data.model_dump(exclude_unset=True)
    now = datetime.now(UTC)
    if payload.get("status") == "sent" and obj.sent_at is None:
        obj.sent_at = now
    if payload.get("status") == "replied" and obj.replied_at is None:
        obj.replied_at = now
    for k, v in payload.items():
        setattr(obj, k, v)
    await db.flush()
    await db.refresh(obj)
    return LinkedInTaskPublic.model_validate(obj)


# ---------- LinkedIn posts ----------


@router.get("/linkedin_posts", response_model=list[LinkedInPostPublic])
async def list_linkedin_posts(auth: CurrentAuth, db: Db) -> list[LinkedInPostPublic]:
    rows = (
        await db.execute(select(LinkedInPost).order_by(LinkedInPost.created_at.desc()))
    ).scalars().all()
    return [LinkedInPostPublic.model_validate(r) for r in rows]


@router.post("/linkedin_posts", response_model=LinkedInPostPublic)
async def create_linkedin_post(
    data: LinkedInPostCreate, auth: CurrentAuth, db: Db
) -> LinkedInPostPublic:
    obj = LinkedInPost(
        id=uuid4(),
        org_id=auth.org_id,
        body=data.body,
        media_urls_json=data.media_urls_json,
        audience=data.audience,
        scheduled_for=data.scheduled_for,
        status="scheduled" if data.scheduled_for else "draft",
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return LinkedInPostPublic.model_validate(obj)


@router.patch("/linkedin_posts/{post_id}", response_model=LinkedInPostPublic)
async def update_linkedin_post(
    post_id: UUID, data: LinkedInPostUpdate, auth: CurrentAuth, db: Db
) -> LinkedInPostPublic:
    obj = await db.get(LinkedInPost, post_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    await db.refresh(obj)
    return LinkedInPostPublic.model_validate(obj)


# ---------- Sequence stats ----------


@router.get("/autopilot/stats", response_model=SequenceStats)
async def autopilot_stats(auth: CurrentAuth, db: Db) -> SequenceStats:
    now = datetime.now(UTC)
    seven_days_ago = now - timedelta(days=7)

    active = (
        await db.execute(
            select(func.count(Enrollment.id)).where(Enrollment.status == "active")
        )
    ).scalar_one()
    sent_7d = (
        await db.execute(
            select(func.count(Message.id)).where(
                Message.sent_at.is_not(None), Message.sent_at >= seven_days_ago
            )
        )
    ).scalar_one()
    replied_7d = (
        await db.execute(
            select(func.count(Message.id)).where(
                Message.replied_at.is_not(None), Message.replied_at >= seven_days_ago
            )
        )
    ).scalar_one()
    end_of_day = now.replace(hour=23, minute=59, second=59)
    queue_today = (
        await db.execute(
            select(func.count(Enrollment.id)).where(
                Enrollment.status == "active",
                Enrollment.next_action_at.is_not(None),
                Enrollment.next_action_at <= end_of_day,
            )
        )
    ).scalar_one()
    next_send = (
        await db.execute(
            select(func.min(Enrollment.next_action_at)).where(
                Enrollment.status == "active",
                Enrollment.next_action_at.is_not(None),
                Enrollment.next_action_at >= now,
            )
        )
    ).scalar_one()
    return SequenceStats(
        active_enrollments=active or 0,
        sent_last_7d=sent_7d or 0,
        replied_last_7d=replied_7d or 0,
        reply_rate=(replied_7d / sent_7d) if sent_7d else 0.0,
        queue_today=queue_today or 0,
        next_send_at=next_send,
    )
