"""Public-facing signing portal at sign.it-gemak.nl.

This router serves both the form UI and accepts submissions. No auth.

Endpoints:
  GET  /sign/                 -- single-page HTML form
  POST /sign/api/kvk-lookup   -- NAW prefill from KvK number (optional)
  POST /sign/api/iban-validate -- quick IBAN syntax/check
  POST /sign/api/submit       -- accept the signed mandate

Internal admin endpoints (auth via existing platform token):
  GET  /sign/admin/list       -- list submitted mandates
  GET  /sign/admin/{id}/pdf   -- download a stored PDF

The submit endpoint:
  * Pydantic-validates every field
  * Generates a UMR (Unique Mandate Reference)
  * Captures IP + user-agent + geo (best-effort)
  * Verifies the debtor's KvK number against IT-gemak's KVK integration
    using the router (OpenKVK primary, official KVK as fallback)
  * Renders the PDF via salespilot.signing.pdf
  * Stores PDF on disk + SHA-256 hash in DB
  * Emails the PDF as attachment to administratie@it-gemak.nl AND to
    the debtor for their records
  * Returns {ok: true, umr, id} on success
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select

from salespilot.config import get_settings
from salespilot.db import raw_session, tenant_session
from salespilot.models.auth import Organization
from salespilot.models.integrations import Integration
from salespilot.models.signing import SignedMandate
from salespilot.signing.pdf import render_mandate_pdf, ADMIN_EMAIL


router = APIRouter(prefix="/sign", tags=["signing"])

# Where signed PDFs are persisted. The /var/lib path is mounted from
# /opt/salespilot/data/signed-mandates on the host so they survive
# container rebuilds.
PDF_STORE = Path("/var/lib/salespilot/signed-mandates")
PDF_STORE.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _generate_umr() -> str:
    """ITG-YYYY-XXXX, where XXXX is uppercase hex of the high 16 bits of a UUID."""
    return f"ITG-{datetime.now(UTC).year}-{uuid4().hex[:6].upper()}"


def _normalize_iban(iban: str) -> str:
    return re.sub(r"\s+", "", iban).upper()


_IBAN_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{1,30}$")


def _valid_iban_syntax(iban: str) -> bool:
    n = _normalize_iban(iban)
    if not _IBAN_RE.match(n):
        return False
    if not (15 <= len(n) <= 34):
        return False
    # ISO 7064 mod-97 checksum
    rearranged = n[4:] + n[:4]
    converted = "".join(
        str(ord(c) - 55) if c.isalpha() else c for c in rearranged
    )
    try:
        return int(converted) % 97 == 1
    except ValueError:
        return False


def _client_ip(request: Request) -> str | None:
    # Caddy sets X-Real-IP; X-Forwarded-For is also there as a chain.
    return (
        request.headers.get("x-real-ip")
        or (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        or (request.client.host if request.client else None)
    )


async def _ip_geo(ip: str | None) -> dict[str, Any]:
    """Best-effort geo lookup. We use the free ip-api.com which is fine
    for a few requests per day; no signup. Production should swap for a
    paid provider with SLA."""
    if not ip:
        return {}
    # Skip private/loopback ranges
    if ip.startswith(("10.", "127.", "192.168.", "172.16.", "::1", "fc", "fd")):
        return {}
    try:
        async with httpx.AsyncClient(timeout=4.0) as c:
            r = await c.get(
                f"http://ip-api.com/json/{ip}?fields=status,country,regionName,city,lat,lon"
            )
            if r.status_code != 200:
                return {}
            data = r.json() or {}
            if data.get("status") != "success":
                return {}
            return {
                "geo_country": data.get("country"),
                "geo_region": data.get("regionName"),
                "geo_city": data.get("city"),
                "geo_lat": data.get("lat"),
                "geo_lon": data.get("lon"),
            }
    except Exception:
        return {}


async def _it_gemak_org_id() -> UUID:
    """Resolve the org_id we'll attach every signed mandate to.

    We pick the first non-demo organization in the database; in
    production there's only IT-gemak. Override via env if needed."""
    env_override = os.environ.get("SIGN_PORTAL_ORG_ID")
    if env_override:
        return UUID(env_override)
    async with raw_session() as db:
        org = (
            await db.execute(
                select(Organization).order_by(Organization.created_at).limit(1)
            )
        ).scalar_one_or_none()
        if org is None:
            raise HTTPException(status_code=500, detail="no organization configured")
        return org.id


async def _verify_kvk_naw(
    *, kvk_number: str | None, expected_name: str | None, expected_postcode: str | None,
) -> tuple[bool, dict[str, Any] | None]:
    """Look up the company at KvK (via the existing router) and compare
    name + postcode against what the user typed.

    Returns (verified, raw_response). When kvk_number is empty or the
    integration isn't configured we return (False, None) — the mandate
    still goes through, just without KvK verification."""
    if not kvk_number or len(kvk_number) < 7:
        return False, None
    try:
        from salespilot.integrations.wespennest_sources import KvkSourceRouter
        org_id = await _it_gemak_org_id()
        async with tenant_session(org_id) as db:
            router = await KvkSourceRouter.from_org(db, org_id)
            if router is None:
                return False, None
            result = await router.lookup_by_kvk(kvk_number)
        if result is None:
            return False, {"error": "not_found", "kvk_number": kvk_number}
        # Light fuzzy match: postcode + first 6 chars of company name
        result_name = (result.trade_name or result.name or "").lower()
        result_pc = re.sub(r"\s+", "", str(result.postal_code or "")).upper()
        exp_name = (expected_name or "").lower().strip()
        exp_pc = re.sub(r"\s+", "", (expected_postcode or "")).upper()
        verified = (
            bool(result_name) and (
                exp_name[:6] in result_name or result_name[:6] in exp_name
            )
        )
        if exp_pc and result_pc and exp_pc != result_pc:
            verified = False
        return verified, result.raw
    except Exception as e:  # noqa: BLE001
        return False, {"error": str(e)[:200]}


# ---------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------


class SubmitRequest(BaseModel):
    debtor_name: str = Field(min_length=2, max_length=200)
    debtor_address: str = Field(min_length=4, max_length=255)
    debtor_postcode: str = Field(min_length=4, max_length=20)
    debtor_city: str = Field(min_length=2, max_length=120)
    debtor_country: str = Field(default="Nederland", max_length=80)
    debtor_iban: str = Field(min_length=15, max_length=34)
    debtor_bic: str | None = Field(default=None, max_length=11)
    debtor_email: EmailStr
    debtor_phone: str | None = Field(default=None, max_length=40)
    debtor_kvk: str | None = Field(default=None, max_length=20)
    sign_place: str = Field(min_length=2, max_length=120)
    # Data-URL: "data:image/png;base64,...."
    signature_png_base64: str = Field(min_length=200)
    # Honeypot field — bots usually fill every input
    company_website: str = Field(default="")
    # Acceptance flags
    accept_terms: bool
    accept_audit: bool

    @field_validator("debtor_iban")
    @classmethod
    def _iban(cls, v: str) -> str:
        if not _valid_iban_syntax(v):
            raise ValueError("ongeldig IBAN-nummer")
        return _normalize_iban(v)

    @field_validator("debtor_kvk")
    @classmethod
    def _kvk(cls, v: str | None) -> str | None:
        if not v:
            return v
        n = re.sub(r"\s+", "", v)
        if not n.isdigit() or len(n) < 7:
            raise ValueError("KvK-nummer moet uit minimaal 7 cijfers bestaan")
        return n

    @field_validator("accept_terms")
    @classmethod
    def _terms(cls, v: bool) -> bool:
        if not v:
            raise ValueError("u moet akkoord gaan met de mandaatvoorwaarden")
        return v

    @field_validator("accept_audit")
    @classmethod
    def _audit(cls, v: bool) -> bool:
        if not v:
            raise ValueError("u moet akkoord gaan met de digitale ondertekening en audit trail")
        return v


# ---------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------


@router.post("/api/kvk-lookup")
async def kvk_lookup_endpoint(payload: dict[str, str]) -> JSONResponse:
    """Used by the form to prefill name + address after entering a KvK
    number. Best-effort; failure is OK -- the user just fills it manually."""
    kvk = (payload.get("kvk_number") or "").strip()
    if not kvk or not kvk.isdigit() or len(kvk) < 7:
        raise HTTPException(status_code=400, detail="ongeldig KvK-nummer")
    try:
        from salespilot.integrations.wespennest_sources import KvkSourceRouter
        org_id = await _it_gemak_org_id()
        async with tenant_session(org_id) as db:
            kvk_router = await KvkSourceRouter.from_org(db, org_id)
            if kvk_router is None:
                return JSONResponse({"found": False, "reason": "kvk_not_configured"})
            result = await kvk_router.lookup_by_kvk(kvk)
        if result is None:
            return JSONResponse({"found": False})
        # Build a single-line "Street + number" string from dataclass fields
        street_parts = [result.street or "", result.house_number or ""]
        address = " ".join(p for p in street_parts if p).strip() or None
        return JSONResponse({
            "found": True,
            "name": result.trade_name or result.name,
            "address": address,
            "postcode": result.postal_code,
            "city": result.city,
            "country": result.country or "Nederland",
        })
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"found": False, "error": str(e)[:200]})


@router.post("/api/iban-validate")
async def iban_validate(payload: dict[str, str]) -> dict[str, Any]:
    iban = (payload.get("iban") or "").strip()
    valid = _valid_iban_syntax(iban)
    return {"valid": valid, "normalized": _normalize_iban(iban) if valid else None}


@router.post("/api/submit")
async def submit_mandate(payload: SubmitRequest, request: Request) -> JSONResponse:
    # Honeypot: if a bot filled the hidden company_website field, lie & 200
    if payload.company_website:
        return JSONResponse({"ok": True, "umr": "ITG-XXXX"}, status_code=200)

    org_id = await _it_gemak_org_id()
    umr = _generate_umr()
    now = datetime.now(UTC)
    ip = _client_ip(request)
    ua = request.headers.get("user-agent")
    geo = await _ip_geo(ip)
    kvk_verified, kvk_raw = await _verify_kvk_naw(
        kvk_number=payload.debtor_kvk,
        expected_name=payload.debtor_name,
        expected_postcode=payload.debtor_postcode,
    )

    # Build PDF
    mandate_dict = {
        "umr": umr,
        "debtor_name": payload.debtor_name,
        "debtor_address": payload.debtor_address,
        "debtor_postcode": payload.debtor_postcode,
        "debtor_city": payload.debtor_city,
        "debtor_country": payload.debtor_country,
        "debtor_iban": payload.debtor_iban,
        "debtor_bic": payload.debtor_bic,
        "debtor_email": payload.debtor_email,
        "debtor_phone": payload.debtor_phone,
        "debtor_kvk": payload.debtor_kvk,
        "sign_place": payload.sign_place,
        "signature_png_base64": payload.signature_png_base64,
        "signed_at": now,
    }
    audit_dict = {
        "ip_address": ip,
        "user_agent": ua,
        **geo,
        "kvk_verified": kvk_verified,
        "kvk_verified_at": now if kvk_verified else None,
    }
    pdf_bytes = render_mandate_pdf(mandate=mandate_dict, audit=audit_dict)
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    pdf_path = PDF_STORE / f"{umr}.pdf"
    pdf_path.write_bytes(pdf_bytes)

    # Persist
    mandate_id = uuid4()
    async with raw_session() as db:
        row = SignedMandate(
            id=mandate_id,
            org_id=org_id,
            umr=umr,
            debtor_name=payload.debtor_name,
            debtor_address=payload.debtor_address,
            debtor_postcode=payload.debtor_postcode,
            debtor_city=payload.debtor_city,
            debtor_country=payload.debtor_country,
            debtor_iban=payload.debtor_iban,
            debtor_bic=payload.debtor_bic,
            debtor_email=payload.debtor_email,
            debtor_phone=payload.debtor_phone,
            debtor_kvk=payload.debtor_kvk,
            sign_place=payload.sign_place,
            signature_png_base64=payload.signature_png_base64,
            ip_address=ip,
            user_agent=ua,
            geo_country=geo.get("geo_country"),
            geo_region=geo.get("geo_region"),
            geo_city=geo.get("geo_city"),
            geo_lat=geo.get("geo_lat"),
            geo_lon=geo.get("geo_lon"),
            kvk_verified=kvk_verified,
            kvk_verified_at=now if kvk_verified else None,
            kvk_raw=kvk_raw,
            pdf_path=str(pdf_path),
            pdf_sha256=pdf_hash,
            status="submitted",
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        await db.commit()

    # Email PDF to administratie + to debtor
    email_error: str | None = None
    try:
        await _send_mandate_email(
            umr=umr,
            debtor=payload,
            pdf_bytes=pdf_bytes,
            kvk_verified=kvk_verified,
        )
        # mark as emailed
        async with raw_session() as db:
            r = await db.get(SignedMandate, mandate_id)
            if r is not None:
                r.status = "emailed"
                r.emailed_at = datetime.now(UTC)
                await db.commit()
    except Exception as e:  # noqa: BLE001
        email_error = str(e)[:500]
        async with raw_session() as db:
            r = await db.get(SignedMandate, mandate_id)
            if r is not None:
                r.email_error = email_error
                await db.commit()

    return JSONResponse({
        "ok": True,
        "umr": umr,
        "id": str(mandate_id),
        "kvk_verified": kvk_verified,
        "pdf_sha256": pdf_hash,
        "email_sent": email_error is None,
        "email_error": email_error,
    })


async def _send_mandate_email(
    *, umr: str, debtor: SubmitRequest, pdf_bytes: bytes, kvk_verified: bool,
) -> None:
    """Send the signed PDF to administratie@it-gemak.nl and a copy to
    the debtor for their own records."""
    from salespilot.integrations.mailgun import MailgunClient, MailgunCredentials

    org_id = await _it_gemak_org_id()
    async with tenant_session(org_id) as db:
        integ = (
            await db.execute(
                select(Integration).where(Integration.kind == "mailgun")
            )
        ).scalar_one_or_none()
    if integ is None or not integ.is_enabled:
        raise RuntimeError("Mailgun integratie niet actief")

    cfg = integ.config_json or {}
    creds = MailgunCredentials(
        api_key=cfg.get("api_key", ""),
        domain=cfg.get("domain", "mail.it-gemak.nl"),
        base_url=cfg.get("base_url", "https://api.eu.mailgun.net"),
    )
    from_name = cfg.get("default_from_name") or "IT-gemak Ondertekenportaal"
    from_email = cfg.get("default_from_email") or f"noreply@{creds.domain}"
    from_full = f"{from_name} <{from_email}>"

    attachment = (f"SEPA-mandaat-{umr}.pdf", pdf_bytes, "application/pdf")
    kvk_line = (
        f"KvK-controle: GESLAAGD voor KvK {debtor.debtor_kvk}"
        if kvk_verified and debtor.debtor_kvk
        else "KvK-controle: niet uitgevoerd (geen KvK opgegeven of geen match)"
    )
    body_admin = (
        f"Nieuw ondertekend SEPA-incassomandaat ontvangen.\n\n"
        f"Mandaatreferentie (UMR): {umr}\n"
        f"Naam: {debtor.debtor_name}\n"
        f"Adres: {debtor.debtor_address}, {debtor.debtor_postcode} {debtor.debtor_city}\n"
        f"IBAN: {debtor.debtor_iban}\n"
        f"E-mail: {debtor.debtor_email}\n"
        f"Telefoon: {debtor.debtor_phone or '-'}\n"
        f"KvK: {debtor.debtor_kvk or '-'}\n"
        f"Plaats van ondertekening: {debtor.sign_place}\n\n"
        f"{kvk_line}\n\n"
        f"Het volledige mandaat plus audit trail vind je in de bijlage.\n"
    )
    body_debtor = (
        f"Beste {debtor.debtor_name},\n\n"
        f"Bedankt voor het ondertekenen van het SEPA-incassomandaat voor IT-gemak B.V.\n"
        f"Uw mandaatreferentie is: {umr}\n\n"
        f"In de bijlage vindt u een kopie van het door u ondertekende document.\n"
        f"Bewaar dit goed -- u heeft het nodig bij eventuele vragen of een herroeping.\n\n"
        f"Met vriendelijke groet,\n"
        f"IT-gemak B.V.\n"
        f"{ADMIN_EMAIL} | 030 - 737 0836\n"
    )

    async with MailgunClient(creds) as mg:
        # To admin
        await mg.send(
            from_full=from_full,
            to=ADMIN_EMAIL,
            subject=f"Nieuw SEPA-mandaat: {umr} ({debtor.debtor_name})",
            body_text=body_admin,
            reply_to=debtor.debtor_email,
            tags=["sign-portal", "sepa-mandate"],
            attachments=[attachment],
        )
        # To debtor (copy)
        await mg.send(
            from_full=from_full,
            to=debtor.debtor_email,
            subject=f"Uw SEPA-incassomandaat IT-gemak ({umr})",
            body_text=body_debtor,
            reply_to=ADMIN_EMAIL,
            tags=["sign-portal", "sepa-mandate-copy"],
            attachments=[attachment],
        )


# ---------------------------------------------------------------------
# Static HTML form -- served at /sign/
# ---------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def sign_form() -> HTMLResponse:
    html = _read_static("sign_form.html")
    return HTMLResponse(html)


@router.get("/health")
async def sign_health() -> dict[str, str]:
    return {"ok": "yes", "portal": "sign.it-gemak.nl"}


def _read_static(name: str) -> str:
    here = Path(__file__).parent.parent / "signing" / "static"
    return (here / name).read_text(encoding="utf-8")
