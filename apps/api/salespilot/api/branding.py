"""Branding: per-org logo upload + brand colour management.

Logo files are stored under /var/lib/salespilot/uploads/ inside the API
container (volume-mounted from the host). They are served read-only by
the API at GET /api/v1/uploads/{filename}.
"""

import os
import secrets
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from salespilot.deps import CurrentAuth, Db
from salespilot.models.auth import Organization
from salespilot.schemas.auth import OrgPublic, OrgUpdate

router = APIRouter(prefix="/branding", tags=["branding"])
uploads_router = APIRouter(prefix="/uploads", tags=["uploads"])


UPLOAD_DIR = Path(os.environ.get("UPLOADS_DIR", "/var/lib/salespilot/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".svg", ".webp"}
MAX_BYTES = 2 * 1024 * 1024  # 2 MB


@router.get("/org", response_model=OrgPublic)
async def get_org(auth: CurrentAuth, db: Db) -> OrgPublic:
    org = await db.get(Organization, auth.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="org not found")
    return OrgPublic.model_validate(org)


@router.patch("/org", response_model=OrgPublic)
async def update_org(data: OrgUpdate, auth: CurrentAuth, db: Db) -> OrgPublic:
    org = await db.get(Organization, auth.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="org not found")
    if data.name is not None and data.name.strip():
        org.name = data.name.strip()[:120]
    if data.brand_color is not None:
        # Accept either '#RRGGBB' or empty string (clear).
        bc = data.brand_color.strip()
        if bc and not bc.startswith("#"):
            bc = "#" + bc
        org.brand_color = bc or None
    await db.flush()
    await db.refresh(org)
    return OrgPublic.model_validate(org)


@router.post("/org/logo", response_model=OrgPublic)
async def upload_org_logo(
    auth: CurrentAuth, db: Db, file: UploadFile = File(...)
) -> OrgPublic:
    org = await db.get(Organization, auth.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="org not found")

    # Validate extension based on filename (cheap) + sniff first bytes (safer).
    name = file.filename or ""
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if ext not in ALLOWED_EXT:
        raise HTTPException(
            status_code=400, detail=f"Only {sorted(ALLOWED_EXT)} accepted"
        )

    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="File too large (max 2 MB)")

    # Filename collision-safe: org_id + random suffix.
    fname = f"logo-{org.id}-{secrets.token_hex(4)}{ext}"
    fpath = UPLOAD_DIR / fname
    fpath.write_bytes(data)

    # Best effort: remove the previous logo file if it lived under our dir.
    if org.logo_url:
        prev = org.logo_url.rsplit("/", 1)[-1]
        prev_path = UPLOAD_DIR / prev
        if prev_path.is_file() and prev_path.resolve().is_relative_to(UPLOAD_DIR.resolve()):
            try:
                prev_path.unlink()
            except OSError:
                pass

    org.logo_url = f"/api/v1/uploads/{fname}"
    await db.flush()
    await db.refresh(org)
    return OrgPublic.model_validate(org)


@router.delete("/org/logo", response_model=OrgPublic)
async def delete_org_logo(auth: CurrentAuth, db: Db) -> OrgPublic:
    org = await db.get(Organization, auth.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="org not found")
    if org.logo_url:
        prev = org.logo_url.rsplit("/", 1)[-1]
        prev_path = UPLOAD_DIR / prev
        if prev_path.is_file() and prev_path.resolve().is_relative_to(UPLOAD_DIR.resolve()):
            try:
                prev_path.unlink()
            except OSError:
                pass
    org.logo_url = None
    await db.flush()
    await db.refresh(org)
    return OrgPublic.model_validate(org)


@uploads_router.get("/{filename}")
async def get_upload(filename: str) -> FileResponse:
    # Strip any path components — we only allow flat filenames.
    safe = Path(filename).name
    if safe != filename or not safe:
        raise HTTPException(status_code=400, detail="bad filename")
    fpath = UPLOAD_DIR / safe
    if not fpath.is_file():
        raise HTTPException(status_code=404, detail="not found")
    # Ensure it really sits inside UPLOAD_DIR (no symlink escapes).
    try:
        fpath.resolve().relative_to(UPLOAD_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="bad path")
    return FileResponse(fpath)
