"""Real Wespennest scanner implementations.

These functions replace the stubs in wespennest_pipeline.py.

Module map:
    scan_domain_m365()           -> M365 detection via MX records
    scan_domain_msp_fingerprint() -> MSP detection via NS/SPF/autodiscover
    scan_kvk_geofilter()         -> KVK lookup + PDOK geocode + distance filter
    scan_decision_makers()       -> KVK Functionarissen + email pattern + SMTP probe
    scan_overname_signals()      -> RSS poll of NL IT news, Claude classifier

Each is async and accepts (db, org_id) plus its own job-specific args.
They write to the wn_* tables and return a counters dict matching the
shape that wespennest_pipeline._record_run expects.
"""

from __future__ import annotations

import asyncio
import math
import os
import re
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from salespilot.integrations.wespennest_sources import (
    CrtShClient,
    KvkSourceRouter,
    PdokClient,
)
from salespilot.models.wespennest import (
    WnAcquisitionSignal,
    WnDecisionMaker,
    WnDomain,
    WnDomainSignals,
    WnDomainKvk,
    WnKvkCompany,
    WnMsp,
    WnMspFingerprint,
    WnVendorAttribution,
)


# ---------------------------------------------------------------------------
# DNS helpers (non-blocking via aiodns when available, fallback to socket)
# ---------------------------------------------------------------------------


async def _resolve_records(name: str, record_type: str) -> list[str]:
    """Resolve DNS records of the given type. Best effort.

    Uses Python's blocking socket.getaddrinfo for A/AAAA, and shells out
    to /usr/bin/dig for the rest because asyncio-native DNS clients are
    not in our minimal image. The 'dig' command is in bind9-dnsutils.
    """
    record_type = record_type.upper()
    if record_type in ("A", "AAAA"):
        try:
            loop = asyncio.get_event_loop()
            family = socket.AF_INET if record_type == "A" else socket.AF_INET6
            infos = await loop.getaddrinfo(name, None, family=family)
            return sorted({i[4][0] for i in infos})
        except Exception:
            return []
    # MX, TXT, NS, CNAME via dig
    try:
        proc = await asyncio.create_subprocess_exec(
            "dig", "+short", "+time=3", "+tries=1", record_type, name,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        lines = [ln.strip() for ln in stdout.decode("utf-8", "ignore").splitlines() if ln.strip()]
        return lines
    except Exception:
        return []


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# 1. M365 scanner
# ---------------------------------------------------------------------------


_M365_MX_PATTERN = re.compile(r"\.mail\.protection\.outlook\.com\.?$", re.IGNORECASE)
_M365_AUTODISC_PATTERN = re.compile(r"autodiscover\.outlook\.com\.?$", re.IGNORECASE)
_GSUITE_MX_PATTERN = re.compile(r"\.google(mail)?\.com\.?$", re.IGNORECASE)
_KPN_MX_PATTERN = re.compile(r"\.(kpn|xs4all)\.(net|nl)\.?$", re.IGNORECASE)


@dataclass
class _M365Result:
    uses_m365: bool
    mail_provider: str
    confidence: int
    mx_records: list[str]


async def _classify_domain_mail(domain: str) -> _M365Result:
    mx_lines = await _resolve_records(domain, "MX")
    # MX lines look like '10 contoso-com.mail.protection.outlook.com.'
    mx_hosts: list[str] = []
    for ln in mx_lines:
        parts = ln.split()
        if len(parts) >= 2:
            mx_hosts.append(parts[-1].rstrip("."))
    if not mx_hosts:
        # Fall back to autodiscover CNAME -- M365 tenant trail
        cn = await _resolve_records(f"autodiscover.{domain}", "CNAME")
        if any(_M365_AUTODISC_PATTERN.search(c.rstrip(".")) for c in cn):
            return _M365Result(True, "microsoft365", 70, [])
        return _M365Result(False, "unknown", 0, [])
    if any(_M365_MX_PATTERN.search(h) for h in mx_hosts):
        return _M365Result(True, "microsoft365", 95, mx_hosts)
    if any(_GSUITE_MX_PATTERN.search(h) for h in mx_hosts):
        return _M365Result(False, "google_workspace", 90, mx_hosts)
    if any(_KPN_MX_PATTERN.search(h) for h in mx_hosts):
        return _M365Result(False, "kpn_xs4all", 80, mx_hosts)
    return _M365Result(False, "other", 50, mx_hosts)


async def scan_domain_m365(
    db: AsyncSession, org_id: UUID, max_domains: int = 50
) -> dict[str, Any]:
    """For each WnDomain with status='pending', detect M365 usage from MX.

    Side effects:
      * Update WnDomain.status to 'scanned' (if M365) or 'rejected' (if not).
      * Insert/update a WnDomainSignals row with the mail provider.
    """
    pending = (
        await db.execute(
            select(WnDomain).where(WnDomain.status == "pending").limit(max_domains)
        )
    ).scalars().all()

    processed = 0
    m365_found = 0
    rejected = 0
    now = datetime.now(UTC)

    for d in pending:
        processed += 1
        try:
            result = await _classify_domain_mail(d.domain)
        except Exception:
            d.status = "error"
            d.last_scanned = now
            await db.flush()
            continue

        # Upsert signals row
        sig = (
            await db.execute(
                select(WnDomainSignals).where(WnDomainSignals.domain_id == d.id)
            )
        ).scalar_one_or_none()
        mail_block = {
            "provider": result.mail_provider,
            "confidence": result.confidence,
            "mx_records": result.mx_records,
            "is_m365": result.uses_m365,
        }
        if sig is None:
            db.add(
                WnDomainSignals(
                    id=uuid4(),
                    org_id=org_id,
                    domain_id=d.id,
                    scanned_at=now,
                    dns={}, mail=mail_block, web={},
                )
            )
        else:
            sig.mail = {**(sig.mail or {}), **mail_block}
            sig.scanned_at = now

        if result.uses_m365:
            d.status = "scanned"
            m365_found += 1
        else:
            d.status = "rejected"
            rejected += 1
        d.last_scanned = now
        await db.flush()

    return {
        "processed": processed,
        "created": m365_found,
        "failed": rejected,
        "message": (
            f"Scanned {processed} domeinen: {m365_found} gebruiken Microsoft 365, "
            f"{rejected} niet (Google Workspace / KPN / overig)."
        ),
        "details": {"m365": m365_found, "non_m365": rejected},
    }


# ---------------------------------------------------------------------------
# 2. MSP fingerprint
# ---------------------------------------------------------------------------


async def _gather_msp_signals(domain: str) -> dict[str, Any]:
    """Collect the signals we match MSP fingerprints against."""
    ns_task = _resolve_records(domain, "NS")
    txt_task = _resolve_records(domain, "TXT")
    autodisc_task = _resolve_records(f"autodiscover.{domain}", "CNAME")
    mail_task = _resolve_records(f"mail.{domain}", "CNAME")
    portal_task = _resolve_records(f"portal.{domain}", "CNAME")
    ns, txt, autodisc, mailc, portal = await asyncio.gather(
        ns_task, txt_task, autodisc_task, mail_task, portal_task,
        return_exceptions=False,
    )
    return {
        "ns": [n.rstrip(".").lower() for n in ns],
        "txt": [t.lower() for t in txt],
        "spf": [t for t in txt if "spf" in t.lower() or "include:" in t.lower()],
        "autodiscover_cname": [c.rstrip(".").lower() for c in autodisc],
        "mail_cname": [c.rstrip(".").lower() for c in mailc],
        "portal_cname": [c.rstrip(".").lower() for c in portal],
    }


def _match_fingerprint(signals: dict[str, Any], fp_type: str, pattern: str) -> bool:
    p = pattern.lower()
    if fp_type == "ns_pattern":
        return any(p in ns for ns in signals.get("ns", []))
    if fp_type == "spf_include":
        return any(p in t for t in signals.get("spf", []))
    if fp_type == "autodiscover_cname":
        return any(p in c for c in signals.get("autodiscover_cname", []))
    if fp_type == "mail_cname":
        return any(p in c for c in signals.get("mail_cname", []))
    if fp_type == "portal_cname":
        return any(p in c for c in signals.get("portal_cname", []))
    if fp_type == "txt_pattern":
        return any(p in t for t in signals.get("txt", []))
    return False


async def scan_domain_msp_fingerprint(
    db: AsyncSession, org_id: UUID, max_domains: int = 50
) -> dict[str, Any]:
    """Match scanned domains against MSP fingerprints (forward attribution)."""
    domains = (
        await db.execute(
            select(WnDomain).where(WnDomain.status == "scanned").limit(max_domains)
        )
    ).scalars().all()
    fps = (
        await db.execute(select(WnMspFingerprint))
    ).scalars().all()
    if not fps:
        return {
            "processed": len(domains),
            "created": 0,
            "failed": 0,
            "message": "Geen MSP-fingerprints geconfigureerd. Voeg patronen toe in Wespennest -> Fingerprints.",
            "details": {"fingerprints": 0},
        }

    processed = 0
    attributions = 0
    now = datetime.now(UTC)

    for d in domains:
        processed += 1
        signals = await _gather_msp_signals(d.domain)

        # Save raw DNS to WnDomainSignals.dns
        sig = (
            await db.execute(
                select(WnDomainSignals).where(WnDomainSignals.domain_id == d.id)
            )
        ).scalar_one_or_none()
        if sig is None:
            sig = WnDomainSignals(
                id=uuid4(), org_id=org_id, domain_id=d.id, scanned_at=now,
                dns=signals, mail={}, web={},
            )
            db.add(sig)
        else:
            sig.dns = {**(sig.dns or {}), **signals}
            sig.scanned_at = now

        # Match each fingerprint, sum weights per MSP
        per_msp: dict[UUID, dict[str, Any]] = {}
        for fp in fps:
            if _match_fingerprint(signals, fp.signal_type, fp.pattern):
                bucket = per_msp.setdefault(fp.msp_id, {"weight": 0, "rules": []})
                bucket["weight"] += fp.weight
                bucket["rules"].append(f"{fp.signal_type}={fp.pattern}")

        # Record attributions for MSPs that crossed the threshold (>=50)
        for msp_id, info in per_msp.items():
            confidence = min(100, info["weight"])
            if confidence < 50:
                continue
            # Skip if we already have an attribution for this (domain, msp)
            existing = (
                await db.execute(
                    select(WnVendorAttribution).where(
                        WnVendorAttribution.domain_id == d.id,
                        WnVendorAttribution.msp_id == msp_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.confidence = max(existing.confidence, confidence)
                existing.rules_fired = info["rules"]
                existing.attributed_at = now
            else:
                db.add(
                    WnVendorAttribution(
                        id=uuid4(),
                        org_id=org_id,
                        domain_id=d.id,
                        msp_id=msp_id,
                        confidence=confidence,
                        rules_fired=info["rules"],
                        attributed_at=now,
                    )
                )
                attributions += 1
        await db.flush()

    return {
        "processed": processed,
        "created": attributions,
        "failed": 0,
        "message": f"Matched {processed} domeinen tegen {len(fps)} fingerprints. {attributions} nieuwe attributies.",
        "details": {"fingerprints_evaluated": len(fps), "new_attributions": attributions},
    }


# ---------------------------------------------------------------------------
# 3. KVK geo-filter (OpenKVK primary, KVK fallback via router)
# ---------------------------------------------------------------------------


# IT-Gemak HQ: Stationsweg 21, Breukelen
DEFAULT_HQ_LAT = 52.1719
DEFAULT_HQ_LON = 4.9994
DEFAULT_RADIUS_KM = 40.0


async def scan_kvk_geofilter(
    db: AsyncSession,
    org_id: UUID,
    max_companies: int = 50,
    hq_lat: float = DEFAULT_HQ_LAT,
    hq_lon: float = DEFAULT_HQ_LON,
    radius_km: float = DEFAULT_RADIUS_KM,
) -> dict[str, Any]:
    """Enrich WnKvkCompany rows that still lack coordinates: look up at
    OpenKVK/KVK, geocode the address with PDOK, compute km_to_hq, and mark
    out-of-radius candidates inactive.
    """
    router = await KvkSourceRouter.from_org(db, org_id)
    pdok = PdokClient()

    candidates = (
        await db.execute(
            select(WnKvkCompany).where(WnKvkCompany.lat.is_(None)).limit(max_companies)
        )
    ).scalars().all()

    processed = 0
    geocoded = 0
    in_range = 0
    out_of_range = 0
    enriched = 0
    now = datetime.now(UTC)

    for c in candidates:
        processed += 1

        # If we only have a KVK number, fill in the rest from the router
        if not c.handelsnaam or not c.adres:
            try:
                co = await router.lookup_by_kvk(c.kvk_nummer)
            except Exception:
                co = None
            if co:
                c.handelsnaam = co.name
                c.rechtsvorm = co.legal_form or c.rechtsvorm
                addr = " ".join(p for p in [co.street, co.house_number] if p).strip()
                c.adres = addr or c.adres
                c.postcode = co.postal_code or c.postcode
                c.plaats = co.city or c.plaats
                c.sbi_codes = co.sbi_codes or c.sbi_codes
                enriched += 1

        # Geocode via PDOK
        if c.lat is None or c.lon is None:
            query_parts = [c.adres or "", c.postcode or "", c.plaats or ""]
            query = " ".join(p for p in query_parts if p).strip()
            if not query:
                continue
            try:
                coords = await pdok.geocode_address(query)
            except Exception:
                coords = None
            if coords is None:
                continue
            c.lat, c.lon = coords
            geocoded += 1

        # Distance check
        if c.lat is not None and c.lon is not None:
            c.km_to_hq = round(_haversine_km(hq_lat, hq_lon, c.lat, c.lon), 2)
            if c.km_to_hq <= radius_km:
                in_range += 1
            else:
                out_of_range += 1

        c.last_updated = now
        await db.flush()

    return {
        "processed": processed,
        "created": in_range,
        "failed": out_of_range,
        "message": (
            f"{processed} bedrijven verwerkt via {router.primary_label}-primary; "
            f"{enriched} verrijkt, {geocoded} gegeocodeerd, "
            f"{in_range} binnen {radius_km:.0f} km, {out_of_range} buiten bereik."
        ),
        "details": {
            "primary_source": router.primary_label,
            "enriched": enriched,
            "geocoded": geocoded,
            "in_range": in_range,
            "out_of_range": out_of_range,
            "hq": {"lat": hq_lat, "lon": hq_lon, "radius_km": radius_km},
        },
    }


# ---------------------------------------------------------------------------
# 4. Decision-maker finder
# ---------------------------------------------------------------------------


EMAIL_PATTERNS = [
    "{first}.{last}@{domain}",
    "{first}@{domain}",
    "{f}{last}@{domain}",
    "{first}{last}@{domain}",
    "{last}@{domain}",
    "{first}-{last}@{domain}",
]


def _slug(s: str) -> str:
    """Strip diacritics and lowercase for email construction."""
    import unicodedata
    norm = unicodedata.normalize("NFKD", s)
    no_acc = norm.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z]+", "", no_acc.lower())


def _candidate_emails(
    first: str, last: str, domain: str
) -> list[tuple[str, str]]:
    """Return [(email, pattern_name)] for all patterns."""
    f = _slug(first)
    last_clean = _slug(last)
    if not f or not last_clean:
        return []
    out: list[tuple[str, str]] = []
    for pat in EMAIL_PATTERNS:
        email = pat.format(
            first=f, last=last_clean, f=f[0] if f else "",
            domain=domain.lower(),
        )
        if "@" in email and email not in {x[0] for x in out}:
            out.append((email, pat))
    return out


async def _smtp_rcpt_probe(mx_host: str, sender: str, recipient: str, timeout: float = 8.0) -> str | None:
    """Try a minimal SMTP RCPT TO probe. Returns one of:
        'deliverable' / 'undeliverable' / 'unknown'
    Returns None when the connection itself fails (treated as 'unknown').

    This uses smtplib in an executor since smtplib is sync. We keep it
    extremely conservative (no DATA stage) to avoid being treated as a
    spam scanner.
    """
    import smtplib

    def _do() -> str | None:
        try:
            with smtplib.SMTP(mx_host, 25, timeout=timeout) as s:
                s.ehlo("salespilot.local")
                code, _ = s.mail(sender)
                if code >= 400:
                    return "unknown"
                code, _ = s.rcpt(recipient)
                if code == 250:
                    return "deliverable"
                if code in (550, 551, 553):
                    return "undeliverable"
                return "unknown"
        except Exception:
            return None

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _do)


async def scan_decision_makers(
    db: AsyncSession,
    org_id: UUID,
    max_companies: int = 20,
    probe_smtp: bool = False,
) -> dict[str, Any]:
    """For each in-radius KVK company without decision makers yet, pull
    functionarissen via the router and generate candidate emails.

    SMTP RCPT-probing is opt-in (probe_smtp=True). It can get the host
    flagged as a spam scanner if done aggressively, so by default we just
    record the most-likely pattern and leave email_verified='unverified'.
    """
    router = await KvkSourceRouter.from_org(db, org_id)

    # Pick companies that are in-range and have a known plaats but no
    # decision maker yet.
    rows = (
        await db.execute(
            select(WnKvkCompany)
            .where(WnKvkCompany.km_to_hq.is_not(None))
            .where(WnKvkCompany.km_to_hq <= DEFAULT_RADIUS_KM)
            .limit(max_companies)
        )
    ).scalars().all()

    processed = 0
    created = 0
    verified = 0
    now = datetime.now(UTC)

    for company in rows:
        processed += 1
        existing = (
            await db.execute(
                select(WnDecisionMaker).where(WnDecisionMaker.kvk_company_id == company.id)
            )
        ).first()
        if existing is not None:
            continue

        try:
            functs = await router.list_functionarissen(company.kvk_nummer)
        except Exception:
            functs = []
        if not functs:
            continue

        # Find a likely domain to construct emails. We use the WnDomainKvk
        # link table first, then fall back to the company's website domain.
        domain = None
        link = (
            await db.execute(
                select(WnDomain.domain).join(
                    WnDomainKvk, WnDomain.id == WnDomainKvk.domain_id
                ).where(WnDomainKvk.kvk_company_id == company.id).limit(1)
            )
        ).scalar_one_or_none()
        if link:
            domain = link
        # If still no domain, attempt website field via re-fetch
        if not domain:
            try:
                co = await router.lookup_by_kvk(company.kvk_nummer)
                if co and co.website:
                    m = re.search(r"https?://(?:www\.)?([^/]+)", co.website)
                    if m:
                        domain = m.group(1)
            except Exception:
                pass

        for f in functs:
            # Parse name into first/last
            parts = f.full_name.split()
            if len(parts) < 2:
                first, last = parts[0], parts[0]
            else:
                first, last = parts[0], parts[-1]

            # Email candidates if we have a domain
            email = None
            pattern_used = None
            verify_state = "unverified"
            verify_method = None

            if domain:
                candidates = _candidate_emails(first, last, domain)
                # Without probing we just take the first canonical pattern
                if candidates:
                    email, pattern_used = candidates[0]

                if probe_smtp and candidates:
                    # Find the domain's primary MX once
                    mx_lines = await _resolve_records(domain, "MX")
                    mx_hosts = []
                    for ln in mx_lines:
                        ps = ln.split()
                        if len(ps) >= 2:
                            mx_hosts.append(ps[-1].rstrip("."))
                    mx_host = mx_hosts[0] if mx_hosts else None

                    if mx_host:
                        sender = f"noreply@{domain}"  # neutral sender
                        for cand, pat in candidates[:3]:
                            res = await _smtp_rcpt_probe(mx_host, sender, cand)
                            if res == "deliverable":
                                email, pattern_used = cand, pat
                                verify_state = "deliverable"
                                verify_method = "smtp_rcpt"
                                verified += 1
                                break
                            if res == "undeliverable":
                                continue
                        else:
                            # Pattern didn't verify; keep the first guess
                            pass

            db.add(
                WnDecisionMaker(
                    id=uuid4(),
                    org_id=org_id,
                    kvk_company_id=company.id,
                    voornaam=first,
                    tussenvoegsel=None,
                    achternaam=last,
                    functie=f.title or f.role,
                    email=email,
                    email_verified=verify_state,
                    email_verify_method=verify_method,
                    email_pattern_used=pattern_used,
                    source=f.source,
                    created_at=now,
                    updated_at=now,
                )
            )
            created += 1
        await db.flush()

    return {
        "processed": processed,
        "created": created,
        "failed": 0,
        "message": (
            f"{processed} bedrijven verwerkt via {router.primary_label}; "
            f"{created} beslissers toegevoegd, {verified} SMTP-geverifieerd."
        ),
        "details": {
            "primary_source": router.primary_label,
            "smtp_probe_enabled": probe_smtp,
            "verified": verified,
        },
    }


# ---------------------------------------------------------------------------
# 5. Overname-monitor (RSS poll + Claude classifier)
# ---------------------------------------------------------------------------


_RSS_SOURCES = [
    ("computable",       "https://www.computable.nl/rss"),
    ("dutchitchannel",   "https://www.dutchitchannel.nl/feed"),
    ("emerce",           "https://www.emerce.nl/feed"),
    ("mena",             "https://www.mena.nl/feed"),
]


# Keywords that strongly suggest an acquisition or strategic move
_PRIMARY_KEYWORDS = [
    "neemt over", "overgenomen", "overname", "acquisition", "acquires",
    "acquired", "fuseert", "fusie", "merger", "investeerder",
    "private equity", "buy and build", "managed services", "msp",
]


def _looks_relevant(title: str, body: str) -> tuple[bool, list[str]]:
    """Quick keyword pre-filter before paying for Claude classification."""
    haystack = f"{title}\n{body}".lower()
    matched = [k for k in _PRIMARY_KEYWORDS if k in haystack]
    return (len(matched) > 0, matched)


async def _fetch_feed(url: str, timeout: float = 15.0) -> list[dict[str, Any]]:
    """Minimal feed parser — handles RSS 2.0 + Atom. No external deps."""
    import xml.etree.ElementTree as ET

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": "SalesPilot/0.1 (Wespennest)"})
            if not r.is_success:
                return []
            xml = r.text
    except Exception:
        return []

    try:
        root = ET.fromstring(xml)
    except Exception:
        return []

    items: list[dict[str, Any]] = []
    # RSS: <channel><item>...
    for item in root.iter("item"):
        items.append({
            "title": (item.findtext("title") or "").strip(),
            "link": (item.findtext("link") or "").strip(),
            "description": (item.findtext("description") or "").strip(),
            "pubDate": (item.findtext("pubDate") or "").strip(),
        })
    # Atom: <entry>...
    for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
        title = entry.findtext("{http://www.w3.org/2005/Atom}title") or ""
        link_el = entry.find("{http://www.w3.org/2005/Atom}link")
        link = link_el.get("href") if link_el is not None else ""
        summary = entry.findtext("{http://www.w3.org/2005/Atom}summary") or ""
        published = entry.findtext("{http://www.w3.org/2005/Atom}published") or ""
        items.append({
            "title": title.strip(),
            "link": (link or "").strip(),
            "description": summary.strip(),
            "pubDate": published.strip(),
        })

    return items


def _parse_pubdate(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return parsedate_to_datetime(s)
    except Exception:
        pass
    # Atom ISO format
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


@dataclass
class _ClassifiedSignal:
    is_acquisition: bool
    acquired_party: str | None
    acquiring_party: str | None
    summary: str
    confidence: int  # 0-100


async def _classify_with_ai_provider(
    db: AsyncSession, org_id: UUID, title: str, body: str,
) -> tuple[_ClassifiedSignal | None, str | None]:
    """Classify an RSS item via the org's preferred AI provider.

    Uses the generic salespilot.ai.classifier helper, which routes through
    OpenAI or Anthropic based on the wespennest ai_classifier_source
    preference. Returns (None, None) when no provider is configured or all
    attempts failed. Second tuple element is the provider name actually
    used, for logging.
    """
    from salespilot.ai.classifier import classify_with_ai

    system_prompt = (
        "You classify Dutch IT-news items into structured JSON. "
        "Mark is_acquisition=true ONLY when one IT-company actually buys, "
        "merges with, or takes over another IT-company. Investments in "
        "unrelated industries, product launches, hiring news, or vague "
        "announcements do not count."
    )
    user_prompt = (
        f"Title: {title}\n"
        f"Body: {body[:1200]}\n\n"
        "Return JSON only, no preamble:\n"
        "{\n"
        "  \"is_acquisition\": true|false,\n"
        "  \"acquired_party\": \"name of MSP/company being acquired\" or null,\n"
        "  \"acquiring_party\": \"name of acquirer\" or null,\n"
        "  \"summary\": \"1 sentence Dutch summary\",\n"
        "  \"confidence\": 0-100\n"
        "}"
    )

    result = await classify_with_ai(
        db=db, org_id=org_id,
        system_prompt=system_prompt, user_prompt=user_prompt,
        max_tokens=400,
    )
    if result is None:
        return None, None

    try:
        import json
        m = re.search(r"\{.*\}", result.text, re.DOTALL)
        if not m:
            return None, result.provider
        parsed = json.loads(m.group(0))
        return _ClassifiedSignal(
            is_acquisition=bool(parsed.get("is_acquisition")),
            acquired_party=parsed.get("acquired_party"),
            acquiring_party=parsed.get("acquiring_party"),
            summary=str(parsed.get("summary") or "")[:500],
            confidence=int(parsed.get("confidence") or 0),
        ), result.provider
    except Exception:
        return None, result.provider


async def scan_overname_signals(
    db: AsyncSession,
    org_id: UUID,
    max_items_per_feed: int = 25,
    use_classifier: bool = True,
) -> dict[str, Any]:
    """Poll Dutch IT news RSS feeds, keyword pre-filter, then AI-classify
    matches via OpenAI or Anthropic (chosen by org preference).

    use_classifier=False forces keyword-only mode regardless of config.
    """
    processed = 0
    relevant = 0
    created = 0
    classified_yes = 0
    skipped_dup = 0
    classifier_used = False
    classifier_provider: str | None = None

    # Pull existing URLs once so we don't write duplicates
    existing_urls = set(
        (
            await db.execute(select(WnAcquisitionSignal.source_url))
        ).scalars().all()
    )

    for source_name, url in _RSS_SOURCES:
        items = await _fetch_feed(url)
        for item in items[:max_items_per_feed]:
            processed += 1
            title = item.get("title") or ""
            link = item.get("link") or ""
            body = item.get("description") or ""
            if not link:
                continue
            if link in existing_urls:
                skipped_dup += 1
                continue

            ok, matched = _looks_relevant(title, body)
            if not ok:
                continue
            relevant += 1

            classified: _ClassifiedSignal | None = None
            if use_classifier:
                classified, provider = await _classify_with_ai_provider(
                    db, org_id, title, body,
                )
                if classified is not None:
                    classifier_used = True
                    classifier_provider = provider

            # Decide whether to record. If Claude classified it as acquisition,
            # always. If no Claude, fall back to keyword-only (lower confidence).
            should_record = False
            confidence = 0
            if classified is not None:
                should_record = classified.is_acquisition
                confidence = classified.confidence
            else:
                should_record = len(matched) >= 2  # 2+ kw matches as proxy
                confidence = 40

            if not should_record:
                continue

            pub = _parse_pubdate(item.get("pubDate") or "")
            db.add(
                WnAcquisitionSignal(
                    id=uuid4(),
                    org_id=org_id,
                    source=source_name,
                    source_url=link,
                    title=title[:500],
                    excerpt=(classified.summary if classified else body[:500]),
                    published_at=pub,
                    status="new",
                    matched_keywords=matched,
                )
            )
            existing_urls.add(link)
            created += 1
            if classified and classified.is_acquisition:
                classified_yes += 1

        # Be polite to the RSS hosts between feeds
        await asyncio.sleep(0.5)

    await db.flush()
    return {
        "processed": processed,
        "created": created,
        "failed": 0,
        "message": (
            f"Gepolld {len(_RSS_SOURCES)} feeds, {processed} items, "
            f"{relevant} keyword-matches, {created} signalen geregistreerd"
            + (
                f" ({classified_yes} door {classifier_provider or 'AI'} bevestigd)"
                if classifier_used else " (keyword-only)"
            )
            + (f", {skipped_dup} duplicaten overgeslagen." if skipped_dup else ".")
        ),
        "details": {
            "feeds": [s[0] for s in _RSS_SOURCES],
            "classifier_used": classifier_used,
            "classifier_provider": classifier_provider,
            "duplicates_skipped": skipped_dup,
        },
    }
