"""Mail-autopilot models: sequences, steps, enrollments, messages.

Also: LinkedIn outreach tasks, LinkedIn posts, mail suppression.

These all live under multi-tenant RLS. Read TenantScoped's notes carefully
— `org_id` is enforced both by RLS policy and by app-side filtering.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from salespilot.models import Base, TenantScoped, Timestamps, UUIDPrimaryKey


class Sequence(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    """A campaign: ordered list of steps + run policy."""

    __tablename__ = "sequences"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    # Auto-enrol bucket: 'hot', 'warm', 'cold', or NULL for manual-only.
    auto_enroll_bucket: Mapped[str | None] = mapped_column(String(10))
    auto_enroll_min_score: Mapped[int | None] = mapped_column(Integer)
    auto_enroll_max_score: Mapped[int | None] = mapped_column(Integer)
    from_name: Mapped[str] = mapped_column(String(120), default="Sales", nullable=False)
    from_email: Mapped[str] = mapped_column(String(200), nullable=False)
    reply_to_email: Mapped[str | None] = mapped_column(String(200))
    daily_limit: Mapped[int] = mapped_column(Integer, default=25, nullable=False)
    send_window_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    cooldown_hours: Mapped[int] = mapped_column(Integer, default=48, nullable=False)
    stop_on_reply: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SequenceStep(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    """A single step. `kind` selects channel + intent."""

    __tablename__ = "sequence_steps"

    sequence_id: Mapped[UUID] = mapped_column(nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # 'email' | 'linkedin_connect' | 'linkedin_dm' | 'linkedin_like' | 'linkedin_visit'
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    wait_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    template_subject: Mapped[str | None] = mapped_column(Text)
    template_body: Mapped[str | None] = mapped_column(Text)
    reply_in_thread: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Enrollment(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    """One prospect + one sequence. status drives the scheduler.

    next_action_at is the timestamp the scheduler looks at. It moves forward
    as we complete steps (current_step_position+1, recompute next_action_at).
    """

    __tablename__ = "enrollments"

    sequence_id: Mapped[UUID] = mapped_column(nullable=False)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    contact_id: Mapped[UUID | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    # active | paused | replied | stopped | done | bounced
    current_step_position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    score_at_enroll: Mapped[int | None] = mapped_column(Integer)
    bucket_at_enroll: Mapped[str | None] = mapped_column(String(10))
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_reason: Mapped[str | None] = mapped_column(String(120))


class Message(UUIDPrimaryKey, TenantScoped, Base):
    """One outbound message attempt (mail or LinkedIn).

    `external_id` for email is Mailgun's Message-Id (without angle brackets).
    `thread_message_id` ties follow-up emails to the original thread.
    """

    __tablename__ = "messages"

    enrollment_id: Mapped[UUID] = mapped_column(nullable=False)
    step_id: Mapped[UUID] = mapped_column(nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # email | linkedin
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    subject: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    to_email: Mapped[str | None] = mapped_column(String(200))
    from_email: Mapped[str | None] = mapped_column(String(200))
    external_id: Mapped[str | None] = mapped_column(String(200))
    thread_message_id: Mapped[str | None] = mapped_column(String(200))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LinkedInTask(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    """Outreach task queued for manual / external execution.

    The system never auto-sends LinkedIn actions. A task gets a status from
    the user (or via an external integration webhook) once it's been
    performed.
    """

    __tablename__ = "linkedin_tasks"

    enrollment_id: Mapped[UUID | None] = mapped_column()
    step_id: Mapped[UUID | None] = mapped_column()
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    contact_id: Mapped[UUID | None] = mapped_column()
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="todo", nullable=False)
    # todo | sent | connected | replied | skipped
    suggested_text: Mapped[str | None] = mapped_column(Text)
    profile_url: Mapped[str | None] = mapped_column(Text)
    post_url: Mapped[str | None] = mapped_column(Text)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class MailSuppression(UUIDPrimaryKey, TenantScoped, Base):
    __tablename__ = "mail_suppression"

    email: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    source_message_id: Mapped[UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LinkedInPost(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    __tablename__ = "linkedin_posts"

    body: Mapped[str] = mapped_column(Text, nullable=False)
    media_urls_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    audience: Mapped[str] = mapped_column(String(20), default="PUBLIC", nullable=False)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(200))
    error: Mapped[str | None] = mapped_column(Text)
