"""Personal calendar API.

Endpoints (all auth-gated, per-user scope):

  GET    /calendar/events?from=YYYY-MM-DD&to=YYYY-MM-DD
  POST   /calendar/events            -- create one-off event
  PATCH  /calendar/events/{id}       -- update title/time/notes/kind
  DELETE /calendar/events/{id}

  GET    /calendar/recurrences
  POST   /calendar/recurrences       -- single template
  POST   /calendar/recurrences/import      -- multiline tekst -> templates
  POST   /calendar/recurrences/{id}/materialize?weeks=4
  PATCH  /calendar/recurrences/{id}
  DELETE /calendar/recurrences/{id}

  PUT    /calendar/events/{id}/reflection -- log green/yellow/red + note
  DELETE /calendar/events/{id}/reflection

  GET    /calendar/day-summary?date=YYYY-MM-DD  -- counts + streak

Every read/write enforces user_id == auth.user_id. We deliberately do
NOT trust org_id here: an admin in the same org cannot read another
user's events through this router.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, select

from salespilot.calendar.parser import (
    bitmask_to_weekdays,
    parse_schedule_text,
    weekdays_to_bitmask,
)
from salespilot.deps import CurrentAuth, Db
from salespilot.models.calendar import (
    CalendarEvent,
    EventReflection,
    RecurrenceTemplate,
)


router = APIRouter(prefix="/calendar", tags=["calendar"])

EUROPE_AMSTERDAM = ZoneInfo("Europe/Amsterdam")


# ---------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------


class EventPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    notes: str | None = None
    kind: str
    color_hex: str | None = None
    start_at: datetime
    end_at: datetime
    all_day: bool = False
    location: str | None = None
    recurrence_template_id: UUID | None = None
    outlook_event_id: str | None = None
    reflection_outcome: str | None = None
    reflection_note: str | None = None


class EventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    notes: str | None = None
    kind: str = "other"
    color_hex: str | None = None
    start_at: datetime
    end_at: datetime
    all_day: bool = False
    location: str | None = None


class EventUpdate(BaseModel):
    title: str | None = None
    notes: str | None = None
    kind: str | None = None
    color_hex: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    all_day: bool | None = None
    location: str | None = None


class RecurrencePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    kind: str
    color_hex: str | None = None
    notes: str | None = None
    location: str | None = None
    weekdays: list[int]
    weekdays_label: str
    start_time: time
    end_time: time
    start_date: date | None = None
    end_date: date | None = None
    is_active: bool = True


class RecurrenceCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    kind: str = "other"
    color_hex: str | None = None
    notes: str | None = None
    location: str | None = None
    weekdays: list[int] = Field(min_length=1)  # 0=Mon..6=Sun
    start_time: time
    end_time: time
    start_date: date | None = None
    end_date: date | None = None


class RecurrenceImport(BaseModel):
    text: str
    auto_materialize_weeks: int = 4


class ImportResult(BaseModel):
    created: list[RecurrencePublic] = []
    errors: list[dict[str, str]] = []  # [{line, reason}]
    materialized_event_count: int = 0


class ReflectionInput(BaseModel):
    outcome: str  # green | yellow | red
    note: str | None = None


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


_WEEKDAY_LABELS_NL = ["ma", "di", "wo", "do", "vr", "za", "zo"]


def _weekdays_label(weekdays: list[int]) -> str:
    if not weekdays:
        return ""
    if weekdays == [0, 1, 2, 3, 4]:
        return "Doordeweeks"
    if weekdays == [5, 6]:
        return "Weekend"
    if weekdays == [0, 1, 2, 3, 4, 5, 6]:
        return "Elke dag"
    return ", ".join(_WEEKDAY_LABELS_NL[d] for d in weekdays)


def _to_public_recurrence(r: RecurrenceTemplate) -> RecurrencePublic:
    weekdays = bitmask_to_weekdays(r.weekdays_bitmask)
    return RecurrencePublic(
        id=r.id, title=r.title, kind=r.kind, color_hex=r.color_hex,
        notes=r.notes, location=r.location,
        weekdays=weekdays,
        weekdays_label=_weekdays_label(weekdays),
        start_time=r.start_time, end_time=r.end_time,
        start_date=r.start_date, end_date=r.end_date,
        is_active=r.is_active,
    )


async def _materialize_template(
    db, template: RecurrenceTemplate, weeks: int,
) -> int:
    """Spawn concrete CalendarEvent rows for the next N weeks.

    Skips dates that already have an event with the same
    recurrence_template_id (idempotent re-run). Uses Europe/Amsterdam
    for the wall-clock interpretation of start_time/end_time so DST is
    handled correctly."""
    if weeks <= 0:
        return 0
    today_local = datetime.now(EUROPE_AMSTERDAM).date()
    horizon = today_local + timedelta(weeks=weeks)

    existing = (
        await db.execute(
            select(CalendarEvent.start_at).where(
                CalendarEvent.recurrence_template_id == template.id,
                CalendarEvent.start_at >= datetime.combine(today_local, time.min, tzinfo=EUROPE_AMSTERDAM),
            )
        )
    ).scalars().all()
    existing_dates = {dt.astimezone(EUROPE_AMSTERDAM).date() for dt in existing}

    weekdays = bitmask_to_weekdays(template.weekdays_bitmask)
    spawned = 0
    cur = today_local
    while cur <= horizon:
        if cur.weekday() in weekdays:
            if (template.start_date is None or cur >= template.start_date) and \
               (template.end_date is None or cur <= template.end_date):
                if cur not in existing_dates:
                    start_local = datetime.combine(cur, template.start_time, tzinfo=EUROPE_AMSTERDAM)
                    end_local = datetime.combine(cur, template.end_time, tzinfo=EUROPE_AMSTERDAM)
                    # Handle end < start (overnight) gracefully
                    if end_local <= start_local:
                        end_local += timedelta(days=1)
                    db.add(CalendarEvent(
                        id=uuid4(),
                        user_id=template.user_id,
                        org_id=template.org_id,
                        recurrence_template_id=template.id,
                        title=template.title,
                        notes=template.notes,
                        kind=template.kind,
                        color_hex=template.color_hex,
                        location=template.location,
                        start_at=start_local.astimezone(UTC),
                        end_at=end_local.astimezone(UTC),
                    ))
                    spawned += 1
        cur += timedelta(days=1)
    return spawned


# ---------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------


@router.get("/events", response_model=list[EventPublic])
async def list_events(
    auth: CurrentAuth, db: Db,
    from_: date | None = None,
    to: date | None = None,
) -> list[EventPublic]:
    # FastAPI's query alias for "from" -- accept under the standard name too
    # (the Pydantic V2 way is via dependency, but we keep it inline simple).
    today = datetime.now(EUROPE_AMSTERDAM).date()
    if from_ is None:
        from_ = today - timedelta(days=7)
    if to is None:
        to = today + timedelta(days=28)

    from_dt = datetime.combine(from_, time.min, tzinfo=EUROPE_AMSTERDAM)
    to_dt = datetime.combine(to, time.max, tzinfo=EUROPE_AMSTERDAM)

    rows = (
        await db.execute(
            select(CalendarEvent).where(
                CalendarEvent.user_id == auth.user_id,
                CalendarEvent.start_at >= from_dt,
                CalendarEvent.start_at <= to_dt,
            ).order_by(CalendarEvent.start_at)
        )
    ).scalars().all()

    # Pull reflections in a single query
    ids = [r.id for r in rows]
    refl_by_event: dict[UUID, EventReflection] = {}
    if ids:
        for refl in (
            await db.execute(
                select(EventReflection).where(EventReflection.event_id.in_(ids))
            )
        ).scalars():
            refl_by_event[refl.event_id] = refl

    out: list[EventPublic] = []
    for r in rows:
        refl = refl_by_event.get(r.id)
        out.append(EventPublic(
            id=r.id, title=r.title, notes=r.notes, kind=r.kind,
            color_hex=r.color_hex, start_at=r.start_at, end_at=r.end_at,
            all_day=r.all_day, location=r.location,
            recurrence_template_id=r.recurrence_template_id,
            outlook_event_id=r.outlook_event_id,
            reflection_outcome=refl.outcome if refl else None,
            reflection_note=refl.note if refl else None,
        ))
    return out


@router.post("/events", response_model=EventPublic, status_code=201)
async def create_event(
    payload: EventCreate, auth: CurrentAuth, db: Db,
) -> EventPublic:
    row = CalendarEvent(
        id=uuid4(),
        user_id=auth.user_id,
        org_id=auth.org_id,
        title=payload.title,
        notes=payload.notes,
        kind=payload.kind,
        color_hex=payload.color_hex,
        start_at=payload.start_at,
        end_at=payload.end_at,
        all_day=payload.all_day,
        location=payload.location,
    )
    db.add(row)
    await db.commit()
    return EventPublic.model_validate(row)


@router.patch("/events/{event_id}", response_model=EventPublic)
async def update_event(
    event_id: UUID, payload: EventUpdate, auth: CurrentAuth, db: Db,
) -> EventPublic:
    row = await db.get(CalendarEvent, event_id)
    if row is None or row.user_id != auth.user_id:
        raise HTTPException(status_code=404, detail="event not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    row.updated_at = datetime.now(UTC)
    await db.commit()
    return EventPublic.model_validate(row)


@router.delete("/events/{event_id}", status_code=204)
async def delete_event(event_id: UUID, auth: CurrentAuth, db: Db) -> None:
    row = await db.get(CalendarEvent, event_id)
    if row is None or row.user_id != auth.user_id:
        raise HTTPException(status_code=404, detail="event not found")
    await db.delete(row)
    await db.commit()


# ---------------------------------------------------------------------
# Recurrence templates
# ---------------------------------------------------------------------


@router.get("/recurrences", response_model=list[RecurrencePublic])
async def list_recurrences(auth: CurrentAuth, db: Db) -> list[RecurrencePublic]:
    rows = (
        await db.execute(
            select(RecurrenceTemplate).where(
                RecurrenceTemplate.user_id == auth.user_id,
            ).order_by(RecurrenceTemplate.start_time)
        )
    ).scalars().all()
    return [_to_public_recurrence(r) for r in rows]


@router.post("/recurrences", response_model=RecurrencePublic, status_code=201)
async def create_recurrence(
    payload: RecurrenceCreate, auth: CurrentAuth, db: Db,
) -> RecurrencePublic:
    row = RecurrenceTemplate(
        id=uuid4(),
        user_id=auth.user_id, org_id=auth.org_id,
        title=payload.title, kind=payload.kind, color_hex=payload.color_hex,
        notes=payload.notes, location=payload.location,
        weekdays_bitmask=weekdays_to_bitmask(payload.weekdays),
        start_time=payload.start_time, end_time=payload.end_time,
        start_date=payload.start_date, end_date=payload.end_date,
    )
    db.add(row)
    await db.commit()
    return _to_public_recurrence(row)


@router.post("/recurrences/import", response_model=ImportResult)
async def import_recurrences(
    payload: RecurrenceImport, auth: CurrentAuth, db: Db,
) -> ImportResult:
    """Free-form text -> recurrence templates -> optional materialisation.

    Example POST body:
        {
          "text": "Elke maandag 9:00-9:30 standup\\nDoordeweeks 8:30 ochtendcheck 15min",
          "auto_materialize_weeks": 4
        }
    """
    parsed = parse_schedule_text(payload.text)

    created: list[RecurrenceTemplate] = []
    for tpl in parsed.templates:
        row = RecurrenceTemplate(
            id=uuid4(),
            user_id=auth.user_id, org_id=auth.org_id,
            title=tpl.title, kind=tpl.kind,
            weekdays_bitmask=weekdays_to_bitmask(tpl.weekdays),
            start_time=tpl.start_time, end_time=tpl.end_time,
        )
        db.add(row)
        created.append(row)
    await db.flush()  # need ids for materialisation

    materialised = 0
    if payload.auto_materialize_weeks and payload.auto_materialize_weeks > 0:
        for row in created:
            materialised += await _materialize_template(
                db, row, payload.auto_materialize_weeks,
            )
    await db.commit()

    return ImportResult(
        created=[_to_public_recurrence(r) for r in created],
        errors=[{"line": ln, "reason": rs} for ln, rs in parsed.errors],
        materialized_event_count=materialised,
    )


@router.post("/recurrences/{template_id}/materialize")
async def materialize_recurrence(
    template_id: UUID, auth: CurrentAuth, db: Db, weeks: int = 4,
) -> dict[str, Any]:
    row = await db.get(RecurrenceTemplate, template_id)
    if row is None or row.user_id != auth.user_id:
        raise HTTPException(status_code=404, detail="template not found")
    spawned = await _materialize_template(db, row, weeks)
    await db.commit()
    return {"ok": True, "events_created": spawned}


@router.patch("/recurrences/{template_id}", response_model=RecurrencePublic)
async def update_recurrence(
    template_id: UUID, payload: RecurrenceCreate, auth: CurrentAuth, db: Db,
) -> RecurrencePublic:
    row = await db.get(RecurrenceTemplate, template_id)
    if row is None or row.user_id != auth.user_id:
        raise HTTPException(status_code=404, detail="template not found")
    row.title = payload.title
    row.kind = payload.kind
    row.color_hex = payload.color_hex
    row.notes = payload.notes
    row.location = payload.location
    row.weekdays_bitmask = weekdays_to_bitmask(payload.weekdays)
    row.start_time = payload.start_time
    row.end_time = payload.end_time
    row.start_date = payload.start_date
    row.end_date = payload.end_date
    row.updated_at = datetime.now(UTC)
    await db.commit()
    return _to_public_recurrence(row)


@router.delete("/recurrences/{template_id}", status_code=204)
async def delete_recurrence(
    template_id: UUID, auth: CurrentAuth, db: Db,
    also_delete_future_events: bool = True,
) -> None:
    row = await db.get(RecurrenceTemplate, template_id)
    if row is None or row.user_id != auth.user_id:
        raise HTTPException(status_code=404, detail="template not found")
    if also_delete_future_events:
        now = datetime.now(UTC)
        future = (
            await db.execute(
                select(CalendarEvent).where(
                    CalendarEvent.recurrence_template_id == template_id,
                    CalendarEvent.start_at >= now,
                )
            )
        ).scalars().all()
        for e in future:
            await db.delete(e)
    await db.delete(row)
    await db.commit()


# ---------------------------------------------------------------------
# Reflections
# ---------------------------------------------------------------------


@router.put("/events/{event_id}/reflection", response_model=EventPublic)
async def set_reflection(
    event_id: UUID, payload: ReflectionInput, auth: CurrentAuth, db: Db,
) -> EventPublic:
    event = await db.get(CalendarEvent, event_id)
    if event is None or event.user_id != auth.user_id:
        raise HTTPException(status_code=404, detail="event not found")
    if payload.outcome not in ("green", "yellow", "red"):
        raise HTTPException(status_code=400, detail="outcome must be green/yellow/red")

    refl = (
        await db.execute(
            select(EventReflection).where(EventReflection.event_id == event_id)
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if refl is None:
        refl = EventReflection(
            id=uuid4(),
            event_id=event_id, user_id=auth.user_id,
            outcome=payload.outcome, note=payload.note,
            created_at=now, updated_at=now,
        )
        db.add(refl)
    else:
        refl.outcome = payload.outcome
        refl.note = payload.note
        refl.updated_at = now
    await db.commit()
    return EventPublic(
        id=event.id, title=event.title, notes=event.notes, kind=event.kind,
        color_hex=event.color_hex, start_at=event.start_at, end_at=event.end_at,
        all_day=event.all_day, location=event.location,
        recurrence_template_id=event.recurrence_template_id,
        outlook_event_id=event.outlook_event_id,
        reflection_outcome=refl.outcome, reflection_note=refl.note,
    )


@router.delete("/events/{event_id}/reflection", status_code=204)
async def clear_reflection(event_id: UUID, auth: CurrentAuth, db: Db) -> None:
    event = await db.get(CalendarEvent, event_id)
    if event is None or event.user_id != auth.user_id:
        raise HTTPException(status_code=404, detail="event not found")
    refl = (
        await db.execute(
            select(EventReflection).where(EventReflection.event_id == event_id)
        )
    ).scalar_one_or_none()
    if refl is not None:
        await db.delete(refl)
        await db.commit()


# ---------------------------------------------------------------------
# Day summary (for the day-overview / streak widget)
# ---------------------------------------------------------------------


class DaySummary(BaseModel):
    date: date
    total_events: int = 0
    reflected: int = 0
    green: int = 0
    yellow: int = 0
    red: int = 0
    streak_green_days: int = 0  # consecutive days ending today with at least 1 green


@router.get("/day-summary", response_model=DaySummary)
async def day_summary(
    auth: CurrentAuth, db: Db, date_: date | None = None,
) -> DaySummary:
    target = date_ or datetime.now(EUROPE_AMSTERDAM).date()
    day_start = datetime.combine(target, time.min, tzinfo=EUROPE_AMSTERDAM)
    day_end = datetime.combine(target, time.max, tzinfo=EUROPE_AMSTERDAM)
    rows = (
        await db.execute(
            select(CalendarEvent.id).where(
                CalendarEvent.user_id == auth.user_id,
                CalendarEvent.start_at >= day_start,
                CalendarEvent.start_at <= day_end,
            )
        )
    ).scalars().all()
    refls = []
    if rows:
        refls = (
            await db.execute(
                select(EventReflection).where(
                    EventReflection.event_id.in_(rows),
                )
            )
        ).scalars().all()
    summary = DaySummary(
        date=target, total_events=len(rows), reflected=len(refls),
        green=sum(1 for r in refls if r.outcome == "green"),
        yellow=sum(1 for r in refls if r.outcome == "yellow"),
        red=sum(1 for r in refls if r.outcome == "red"),
    )

    # Streak: walk backwards from today, days with at least 1 green
    streak = 0
    cur = target
    while True:
        ds = datetime.combine(cur, time.min, tzinfo=EUROPE_AMSTERDAM)
        de = datetime.combine(cur, time.max, tzinfo=EUROPE_AMSTERDAM)
        cur_rows = (
            await db.execute(
                select(EventReflection.outcome)
                .join(CalendarEvent, CalendarEvent.id == EventReflection.event_id)
                .where(
                    CalendarEvent.user_id == auth.user_id,
                    CalendarEvent.start_at >= ds,
                    CalendarEvent.start_at <= de,
                )
            )
        ).scalars().all()
        if any(o == "green" for o in cur_rows):
            streak += 1
            cur -= timedelta(days=1)
            if streak > 30:  # cap so we don't loop forever
                break
        else:
            break
    summary.streak_green_days = streak
    return summary
