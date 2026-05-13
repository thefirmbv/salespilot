"""API for the social-content scheduler.

  GET    /social/posts                          list with filters
  POST   /social/posts                          create draft or scheduled
  GET    /social/posts/{id}                     read
  PATCH  /social/posts/{id}                     update
  DELETE /social/posts/{id}                     delete
  POST   /social/posts/{id}/publish-now         force-publish immediately
  POST   /social/posts/{id}/duplicate           clone into a new draft
  GET    /social/posts/summary                  KPI strip
  GET    /social/destinations                   personal + company targets

  POST   /social/media                          upload a file
  DELETE /social/media/{id}                     delete an upload
  GET    /social/media/{id}/file                serve the file binary

  GET    /social/posts/{id}/metrics             list metric snapshots
  POST   /social/posts/{id}/metrics/refresh     pull fresh stats from LinkedIn

  POST   /social/scheduler/tick                 cron-only: publish due posts
"""

from __future__ import annotations

import asyncio
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import desc, func, or_, select

from salespilot.deps import CurrentAuth, Db
from salespilot.integrations.linkedin import (
    LinkedInClient,
    LinkedInError,
    LinkedInPostResult,
    list_destinations_for_token,
)
from salespilot.models.auth import User
from salespilot.models.integrations import Integration
from salespilot.models.social import SocialPost, SocialPostMedia, SocialPostMetrics
from salespilot.schemas.social import (
    Destination,
    LinkedInAccount,
    MediaPublic,
    PostMediaUploadResult,
    PostPublic,
    PostUpdate,
    PostUpsert,
    PostsSummary,
    PublishNowResult,
    PublishResultEntry,
)


router = APIRouter(prefix="/social", tags=["social"])


# Where uploaded media is stored on disk. Volume-mounted in compose:
#   /opt/salespilot/data/social-media  ->  /var/lib/salespilot/social-media
MEDIA_ROOT = Path(
    os.environ.get("SOCIAL_MEDIA_ROOT", "/var/lib/salespilot/social-media")
)
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)


# ----- Helpers -------------------------------------------------------


async def _enrich_post(db: Db, p: SocialPost) -> PostPublic:
    media_rows = (
        await db.execute(
            select(SocialPostMedia)
            .where(SocialPostMedia.post_id == p.id)
            .order_by(SocialPostMedia.position)
        )
    ).scalars().all()
    media = [
        MediaPublic(
            id=m.id,
            position=m.position,
            filename=m.filename,
            mime_type=m.mime_type,
            size_bytes=m.size_bytes,
            alt_text=m.alt_text,
            caption=m.caption,
            url=f"/api/v1/social/media/{m.id}/file",
        )
        for m in media_rows
    ]
    creator_name = None
    if p.created_by:
        u = await db.get(User, p.created_by)
        if u:
            creator_name = u.full_name or u.email

    # Pydantic doesn't auto-cast JSON list -> destination list, so do it manually
    dest = [Destination(**d) for d in (p.destinations or []) if isinstance(d, dict)]
    pub = [PublishResultEntry(**r) for r in (p.publish_result or []) if isinstance(r, dict)]

    return PostPublic(
        id=p.id,
        org_id=p.org_id,
        created_by=p.created_by,
        creator_name=creator_name,
        destinations=dest,
        body=p.body or "",
        title=p.title,
        status=p.status,
        scheduled_at=p.scheduled_at,
        published_at=p.published_at,
        publish_result=pub,
        last_error=p.last_error,
        retry_count=p.retry_count,
        media=media,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


async def _get_linkedin_token(db: Db) -> str:
    from salespilot.api.oauth_callbacks import refresh_linkedin_token_if_needed
    integ = (
        await db.execute(
            select(Integration).where(
                Integration.kind == "linkedin",
                Integration.is_enabled == True,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if integ is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "LinkedIn is niet geconfigureerd. Ga naar Settings → "
                "Integrations → LinkedIn en verbind via OAuth."
            ),
        )
    # Best-effort refresh -- silent if no refresh_token or not yet expiring
    try:
        if await refresh_linkedin_token_if_needed(integ):
            await db.flush()
    except Exception:
        pass
    cfg = integ.config_json or {}
    token = cfg.get("access_token")
    if not token:
        raise HTTPException(
            status_code=400,
            detail="LinkedIn access_token ontbreekt. Verbind LinkedIn via Settings.",
        )
    return token


# ----- Destinations -----


@router.get("/destinations", response_model=list[LinkedInAccount])
async def list_destinations(auth: CurrentAuth, db: Db) -> list[LinkedInAccount]:
    """Return person + organization destinations the user can post to."""
    token = await _get_linkedin_token(db)
    try:
        items = await list_destinations_for_token(token)
    except LinkedInError as e:
        raise HTTPException(status_code=502, detail=f"LinkedIn API: {e}")
    return [LinkedInAccount(**i) for i in items]


# ----- Posts CRUD -----


@router.get("/posts", response_model=list[PostPublic])
async def list_posts(
    auth: CurrentAuth,
    db: Db,
    status: str | None = Query(None, description="comma-separated"),
    from_dt: datetime | None = Query(None),
    to_dt: datetime | None = Query(None),
    limit: int = Query(200, le=500),
) -> list[PostPublic]:
    stmt = select(SocialPost)
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            stmt = stmt.where(SocialPost.status.in_(statuses))
    if from_dt or to_dt:
        # Match posts whose scheduled_at OR published_at falls in the window
        when = func.coalesce(SocialPost.scheduled_at, SocialPost.published_at, SocialPost.created_at)
        if from_dt:
            stmt = stmt.where(when >= from_dt)
        if to_dt:
            stmt = stmt.where(when <= to_dt)
    # Newest first by the most relevant timestamp.
    stmt = stmt.order_by(
        desc(
            func.coalesce(
                SocialPost.published_at, SocialPost.scheduled_at, SocialPost.created_at
            )
        )
    ).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [await _enrich_post(db, p) for p in rows]


@router.get("/posts/summary", response_model=PostsSummary)
async def posts_summary(auth: CurrentAuth, db: Db) -> PostsSummary:
    rows = (await db.execute(select(SocialPost))).scalars().all()
    now = datetime.now(UTC)
    thirty_ago = now - timedelta(days=30)

    drafts = sum(1 for p in rows if p.status == "draft")
    scheduled = sum(1 for p in rows if p.status == "scheduled")
    failed = sum(1 for p in rows if p.status == "failed")
    published_30d = sum(
        1 for p in rows if p.status == "published" and p.published_at and p.published_at >= thirty_ago
    )

    # Sum metrics from the last 30 days
    published_ids = [p.id for p in rows if p.status == "published"]
    impressions_30d = 0
    engagements_30d = 0
    if published_ids:
        # Latest snapshot per post
        sub = (
            select(
                SocialPostMetrics.post_id,
                func.max(SocialPostMetrics.snapshot_at).label("max_at"),
            )
            .where(SocialPostMetrics.post_id.in_(published_ids))
            .group_by(SocialPostMetrics.post_id)
            .subquery()
        )
        metric_rows = (
            await db.execute(
                select(SocialPostMetrics).join(
                    sub,
                    (SocialPostMetrics.post_id == sub.c.post_id)
                    & (SocialPostMetrics.snapshot_at == sub.c.max_at),
                )
            )
        ).scalars().all()
        for m in metric_rows:
            impressions_30d += m.impressions
            engagements_30d += m.likes + m.comments + m.shares + m.clicks

    return PostsSummary(
        total=len(rows),
        drafts=drafts,
        scheduled=scheduled,
        published_30d=published_30d,
        failed=failed,
        impressions_30d=impressions_30d,
        engagements_30d=engagements_30d,
    )


@router.post("/posts", response_model=PostPublic, status_code=201)
async def create_post(data: PostUpsert, auth: CurrentAuth, db: Db) -> PostPublic:
    if data.status == "scheduled" and not data.scheduled_at:
        raise HTTPException(
            status_code=400,
            detail="scheduled_at is verplicht voor ingeplande posts.",
        )
    now = datetime.now(UTC)
    p = SocialPost(
        id=uuid4(),
        org_id=auth.org_id,
        created_by=auth.user_id,
        destinations=[d.model_dump() for d in data.destinations],
        body=data.body,
        title=data.title,
        status=data.status,
        scheduled_at=data.scheduled_at,
        created_at=now,
        updated_at=now,
    )
    db.add(p)
    await db.flush()
    return await _enrich_post(db, p)


@router.get("/posts/{post_id}", response_model=PostPublic)
async def get_post(post_id: UUID, auth: CurrentAuth, db: Db) -> PostPublic:
    p = await db.get(SocialPost, post_id)
    if p is None:
        raise HTTPException(status_code=404)
    return await _enrich_post(db, p)


@router.patch("/posts/{post_id}", response_model=PostPublic)
async def update_post(
    post_id: UUID, data: PostUpdate, auth: CurrentAuth, db: Db
) -> PostPublic:
    p = await db.get(SocialPost, post_id)
    if p is None:
        raise HTTPException(status_code=404)
    if p.status in ("published", "publishing"):
        raise HTTPException(
            status_code=400,
            detail="Een gepubliceerde of bezig-met-publiceren post kan niet meer bewerkt worden. Maak een duplicaat.",
        )
    if data.title is not None:
        p.title = data.title
    if data.body is not None:
        p.body = data.body
    if data.destinations is not None:
        p.destinations = [d.model_dump() for d in data.destinations]
    if data.scheduled_at is not None:
        p.scheduled_at = data.scheduled_at
    if data.status is not None:
        # Validate: can only go draft <-> scheduled <-> cancelled here
        if data.status == "scheduled" and not (data.scheduled_at or p.scheduled_at):
            raise HTTPException(
                status_code=400, detail="scheduled_at is verplicht voor inplannen.",
            )
        p.status = data.status
    await db.flush()
    return await _enrich_post(db, p)


@router.delete("/posts/{post_id}", status_code=204)
async def delete_post(post_id: UUID, auth: CurrentAuth, db: Db) -> None:
    p = await db.get(SocialPost, post_id)
    if p is None:
        raise HTTPException(status_code=404)
    # Also clean media files from disk
    media = (
        await db.execute(
            select(SocialPostMedia).where(SocialPostMedia.post_id == post_id)
        )
    ).scalars().all()
    for m in media:
        try:
            (MEDIA_ROOT / m.storage_path).unlink(missing_ok=True)
        except Exception:
            pass
    await db.delete(p)
    await db.flush()


@router.post("/posts/{post_id}/duplicate", response_model=PostPublic, status_code=201)
async def duplicate_post(post_id: UUID, auth: CurrentAuth, db: Db) -> PostPublic:
    src = await db.get(SocialPost, post_id)
    if src is None:
        raise HTTPException(status_code=404)
    now = datetime.now(UTC)
    p = SocialPost(
        id=uuid4(),
        org_id=auth.org_id,
        created_by=auth.user_id,
        destinations=src.destinations,
        body=src.body,
        title=(src.title or "") + " (kopie)" if src.title else None,
        status="draft",
        scheduled_at=None,
        created_at=now,
        updated_at=now,
    )
    db.add(p)
    await db.flush()

    # Duplicate media too — re-use the same files (cheap, no copy)
    src_media = (
        await db.execute(
            select(SocialPostMedia).where(SocialPostMedia.post_id == post_id)
        )
    ).scalars().all()
    for m in src_media:
        db.add(
            SocialPostMedia(
                id=uuid4(),
                org_id=auth.org_id,
                post_id=p.id,
                uploaded_by=auth.user_id,
                position=m.position,
                filename=m.filename,
                mime_type=m.mime_type,
                size_bytes=m.size_bytes,
                storage_path=m.storage_path,
                alt_text=m.alt_text,
                caption=m.caption,
                created_at=now,
                updated_at=now,
            )
        )
    await db.flush()
    return await _enrich_post(db, p)


# ----- Media -----


@router.post("/media", response_model=PostMediaUploadResult)
async def upload_media(
    auth: CurrentAuth,
    db: Db,
    post_id: UUID | None = Query(None),
    file: UploadFile = File(...),
) -> PostMediaUploadResult:
    if file.content_type and not (
        file.content_type.startswith("image/") or file.content_type.startswith("video/")
    ):
        raise HTTPException(
            status_code=400,
            detail="Alleen afbeeldingen of video's mogen worden geüpload.",
        )
    media_id = uuid4()
    suffix = Path(file.filename or "upload").suffix or ".bin"
    relative = f"{auth.org_id}/{media_id}{suffix}"
    full = MEDIA_ROOT / relative
    full.parent.mkdir(parents=True, exist_ok=True)

    size = 0
    with full.open("wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            out.write(chunk)

    # Decide position: next free slot in the post
    position = 0
    if post_id is not None:
        existing = (
            await db.execute(
                select(func.coalesce(func.max(SocialPostMedia.position), -1))
                .where(SocialPostMedia.post_id == post_id)
            )
        ).scalar() or -1
        position = existing + 1

    now = datetime.now(UTC)
    row = SocialPostMedia(
        id=media_id,
        org_id=auth.org_id,
        post_id=post_id,
        uploaded_by=auth.user_id,
        position=position,
        filename=file.filename or "upload",
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=size,
        storage_path=relative,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.flush()
    return PostMediaUploadResult(
        ok=True,
        media_id=media_id,
        url=f"/api/v1/social/media/{media_id}/file",
        filename=row.filename,
        size_bytes=size,
    )


@router.delete("/media/{media_id}", status_code=204)
async def delete_media(media_id: UUID, auth: CurrentAuth, db: Db) -> None:
    m = await db.get(SocialPostMedia, media_id)
    if m is None:
        raise HTTPException(status_code=404)
    try:
        (MEDIA_ROOT / m.storage_path).unlink(missing_ok=True)
    except Exception:
        pass
    await db.delete(m)
    await db.flush()


@router.get("/media/{media_id}/file")
async def serve_media(media_id: UUID, auth: CurrentAuth, db: Db) -> FileResponse:
    m = await db.get(SocialPostMedia, media_id)
    if m is None:
        raise HTTPException(status_code=404)
    full = MEDIA_ROOT / m.storage_path
    if not full.exists():
        raise HTTPException(status_code=404, detail="file missing on disk")
    return FileResponse(full, media_type=m.mime_type, filename=m.filename)


# ----- Publish -----


async def _publish_one(db: Db, post: SocialPost) -> list[PublishResultEntry]:
    """Internal: actually push a post to every destination. Updates the
    SocialPost row in place. Returns the per-destination results."""
    token = await _get_linkedin_token(db)
    media_rows = (
        await db.execute(
            select(SocialPostMedia)
            .where(SocialPostMedia.post_id == post.id)
            .order_by(SocialPostMedia.position)
        )
    ).scalars().all()

    results: list[PublishResultEntry] = []
    async with LinkedInClient(token) as li:
        for d in post.destinations or []:
            if not isinstance(d, dict):
                continue
            owner_urn = d.get("target_urn")
            if not owner_urn:
                results.append(
                    PublishResultEntry(
                        platform="linkedin", target_urn="",
                        target_name=d.get("target_name"),
                        error="missing target_urn",
                    )
                )
                continue

            # 1) Upload media (we re-use cached asset URN if present)
            image_urns: list[str] = []
            try:
                for m in media_rows:
                    if not m.mime_type.startswith("image/"):
                        continue
                    if m.linkedin_asset_urn:
                        image_urns.append(m.linkedin_asset_urn)
                        continue
                    full = MEDIA_ROOT / m.storage_path
                    if not full.exists():
                        continue
                    file_bytes = full.read_bytes()
                    urn = await li.upload_image(owner_urn, file_bytes, m.mime_type)
                    m.linkedin_asset_urn = urn
                    image_urns.append(urn)
                await db.flush()
            except LinkedInError as e:
                results.append(
                    PublishResultEntry(
                        platform="linkedin",
                        target_urn=owner_urn,
                        target_name=d.get("target_name"),
                        error=f"media upload failed: {e}",
                    )
                )
                continue

            # 2) Create the post
            r: LinkedInPostResult = await li.create_post(
                author_urn=owner_urn,
                commentary=post.body,
                image_urns=image_urns or None,
            )
            results.append(
                PublishResultEntry(
                    platform="linkedin",
                    target_urn=owner_urn,
                    target_name=d.get("target_name"),
                    platform_post_id=r.platform_post_id,
                    post_url=r.post_url,
                    published_at=datetime.now(UTC) if r.ok else None,
                    error=r.error,
                )
            )

    # Aggregate -> update SocialPost
    now = datetime.now(UTC)
    all_ok = all(r.error is None for r in results) and bool(results)
    post.publish_result = [r.model_dump(mode="json") for r in results]
    if all_ok:
        post.status = "published"
        post.published_at = now
        post.last_error = None
    elif any(r.error is None for r in results):
        post.status = "published"  # partial success still counts as published
        post.published_at = now
        post.last_error = "; ".join(
            f"{r.target_name or r.target_urn}: {r.error}" for r in results if r.error
        )
    else:
        post.status = "failed"
        post.retry_count += 1
        post.last_error = "; ".join(
            f"{r.target_name or r.target_urn}: {r.error}" for r in results if r.error
        )
    post.updated_at = now
    await db.flush()
    return results


@router.post("/posts/{post_id}/publish-now", response_model=PublishNowResult)
async def publish_now(post_id: UUID, auth: CurrentAuth, db: Db) -> PublishNowResult:
    p = await db.get(SocialPost, post_id)
    if p is None:
        raise HTTPException(status_code=404)
    if not p.destinations:
        raise HTTPException(
            status_code=400, detail="Geen bestemmingen geselecteerd voor deze post.",
        )
    if not (p.body or "").strip():
        raise HTTPException(status_code=400, detail="De post-tekst is leeg.")
    p.status = "publishing"
    await db.flush()
    results = await _publish_one(db, p)
    return PublishNowResult(
        ok=p.status == "published",
        post_id=p.id,
        detail=(
            "Gepubliceerd op LinkedIn."
            if p.status == "published"
            else f"Publicatie mislukt: {p.last_error or 'onbekend'}"
        ),
        results=results,
    )


# ----- Scheduler tick (cron entry point) -----


@router.post("/scheduler/tick")
async def scheduler_tick(auth: CurrentAuth, db: Db) -> dict[str, Any]:
    """Publish all posts whose scheduled_at is in the past.

    Intended to be hit by cron once per minute. Authenticated like any
    other endpoint, since the cron itself uses a service-account JWT.
    """
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
    published = 0
    failed = 0
    for p in due:
        p.status = "publishing"
        await db.flush()
        try:
            await _publish_one(db, p)
            if p.status == "published":
                published += 1
            else:
                failed += 1
        except Exception as e:  # noqa: BLE001
            p.status = "failed"
            p.last_error = str(e)[:500]
            p.retry_count += 1
            await db.flush()
            failed += 1
    return {
        "ok": True,
        "due": len(due),
        "published": published,
        "failed": failed,
    }


# ----- Metrics -----


@router.get("/posts/{post_id}/metrics")
async def list_metrics(
    post_id: UUID, auth: CurrentAuth, db: Db
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(SocialPostMetrics)
            .where(SocialPostMetrics.post_id == post_id)
            .order_by(SocialPostMetrics.snapshot_at)
        )
    ).scalars().all()
    return [
        {
            "snapshot_at": r.snapshot_at.isoformat(),
            "platform_post_id": r.platform_post_id,
            "impressions": r.impressions,
            "likes": r.likes,
            "comments": r.comments,
            "shares": r.shares,
            "clicks": r.clicks,
            "engagement_rate": r.engagement_rate,
        }
        for r in rows
    ]


@router.post("/posts/{post_id}/metrics/refresh")
async def refresh_metrics(post_id: UUID, auth: CurrentAuth, db: Db) -> dict[str, Any]:
    """Pull fresh stats for each published destination of this post."""
    p = await db.get(SocialPost, post_id)
    if p is None:
        raise HTTPException(status_code=404)
    if p.status != "published":
        raise HTTPException(status_code=400, detail="Post is nog niet gepubliceerd.")
    token = await _get_linkedin_token(db)
    now = datetime.now(UTC)
    inserted = 0
    async with LinkedInClient(token) as li:
        for entry in p.publish_result or []:
            if not isinstance(entry, dict):
                continue
            ppid = entry.get("platform_post_id")
            if not ppid:
                continue
            try:
                stats = await li.get_post_stats(ppid)
            except Exception:  # noqa: BLE001
                continue
            db.add(
                SocialPostMetrics(
                    id=uuid4(),
                    org_id=auth.org_id,
                    post_id=p.id,
                    platform_post_id=ppid,
                    snapshot_at=now,
                    impressions=int(stats.get("impressions") or 0),
                    likes=int(stats.get("likes") or 0),
                    comments=int(stats.get("comments") or 0),
                    shares=int(stats.get("shares") or 0),
                    clicks=int(stats.get("clicks") or 0),
                    raw=stats,
                )
            )
            inserted += 1
    await db.flush()
    return {"ok": True, "snapshots_added": inserted}
