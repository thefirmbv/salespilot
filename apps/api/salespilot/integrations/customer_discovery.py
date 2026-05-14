"""Customer-discovery for overgenomen MSPs.

Goal: find domains that are likely end-customers of an acquired MSP.
After acquisition the customers are in a 'trust window' where they
question the service quality -- that's our outreach moment.

Discovery methods (each can be enabled/disabled independently):

  crtsh_subdomains       Query crt.sh for certificates issued for
                         *.<msp>.nl. Common pattern: MSPs host a portal
                         like portal.<msp>.nl per customer where the
                         subdomain reveals the customer (e.g.
                         klantbedrijf-x.portal.cabholland.nl).

  crtsh_san              Query crt.sh for certificates whose Subject
                         Alternative Names include the MSP domain
                         alongside other domains. When an MSP-managed
                         server holds certs for multiple customer
                         domains, those certs reveal the relationship.

  mx_lookup              For a seed list of NL domains, check whether
                         their MX records point to mail.<msp>.nl. Slow
                         (one DNS query per domain) and requires a
                         candidate domain list to test against, so we
                         keep it opt-in.

  spf_include            For seed domains, check whether their SPF
                         record includes include:<msp-spf-host>.
                         Strong signal: only MSPs that handle mail
                         get included in SPF.

  reseller_substring     Match the MSP name as a substring inside
                         domain names (e.g. 'cabholland-rotterdam.nl').
                         Cheap but noisy; useful for white-label
                         resellers.

All results land in wn_domains with discovery_source labelled as
'msp:<msp-id>:<method>' so we can later show "this customer was found
by method X for MSP Y" in the UI, and let the user confirm/reject.

The crt.sh source (https://crt.sh) is free, has no rate-limit document
but we throttle ourselves to be polite (1 req/sec).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import quote

import httpx
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession


log = logging.getLogger(__name__)


# Domains that turn up in CT logs but are never useful end-customers --
# CDNs, hosting infra, helpdesks, etc. Filter them out before saving.
_BORING_TLDS = {"acme-staging.api.letsencrypt.org", "cloudflare.com", "amazonaws.com"}
_BORING_SUBSTRINGS = [
    "cloudfront.net", "amazonaws", "azurewebsites.net", "azurefd.net",
    "google.com", "googleusercontent.com", "googleapis.com",
    "akamai", "fastly.net", "cdn.", "cdn-", ".local", "letsencrypt",
    "shopify", "wix.com", "weebly.com", "github.io", "netlify.app",
    "vercel.app", "herokuapp.com", "myshopify.com", "wixsite.com",
    "wordpress.com", "tumblr.com", "stackpath", "ngrok",
]
_NL_PRIORITY_TLDS = {".nl", ".com", ".eu", ".net"}


@dataclass(frozen=True)
class CustomerCandidate:
    domain: str          # 'klantbedrijf.nl' (apex, no scheme/subdomain)
    method: str          # 'crtsh_subdomains' | 'crtsh_san' | 'mx_lookup' | 'spf_include' | 'reseller_substring'
    evidence: str        # short human-readable proof (e.g. cert serial, MX target)
    confidence: int      # 0..100


def _extract_apex(host: str) -> str | None:
    """Reduce 'mail.foo.example.com' to 'example.com' for the common case.

    We deliberately don't fight the public suffix problem here; a 'co.uk'
    or '.com.br' is rare in NL MSP customers and the slightly-too-long
    apex still gives a useful per-organisation grouping in practice.
    Returns None for things that don't look like real domains.
    """
    h = (host or "").strip().lower().rstrip(".")
    if not h or " " in h:
        return None
    # crt.sh sometimes lists rows with wildcards or commas -- split & take first
    h = h.split(",")[0].lstrip("*.").strip()
    if h.startswith("*."):
        h = h[2:]
    # Must contain at least one dot and end with a letter
    if "." not in h:
        return None
    if not re.match(r"^[a-z0-9.-]+$", h):
        return None
    parts = h.split(".")
    if len(parts) < 2:
        return None
    # Take last two labels as apex (good enough heuristic for NL).
    apex = ".".join(parts[-2:])
    return apex


def _is_boring(domain: str) -> bool:
    if not domain:
        return True
    for sub in _BORING_SUBSTRINGS:
        if sub in domain:
            return True
    if domain in _BORING_TLDS:
        return True
    if domain.endswith(".local") or domain.endswith(".internal"):
        return True
    return False


def _msp_apex(website: str | None, msp_name: str) -> str | None:
    """Derive the apex domain for an MSP -- prefer the website field,
    fall back to a guess from the name."""
    if website:
        host = re.sub(r"^https?://", "", website.strip(), flags=re.I)
        host = host.split("/")[0].lower()
        apex = _extract_apex(host)
        if apex:
            return apex
    # Guess from name: 'CAB Holland' -> 'cabholland.nl'
    guess = re.sub(r"[^a-z0-9]+", "", msp_name.lower()) + ".nl"
    return _extract_apex(guess)


# ---------------------------------------------------------------------
# crt.sh source
# ---------------------------------------------------------------------


async def _certspotter_dns_names(
    domain: str, include_subdomains: bool = True, timeout: float = 30.0,
) -> list[str]:
    """Query api.certspotter.com for all DNS names appearing on certs
    issued for `domain`. This is our primary CT-log source -- crt.sh
    is unreliable (frequent 502s) so we use Certspotter's free tier
    which returns clean JSON and rarely fails.

    Returns a flat list of lowercased DNS names (deduplicated).
    """
    url = (
        f"https://api.certspotter.com/v1/issuances"
        f"?domain={quote(domain)}"
        f"&include_subdomains={'true' if include_subdomains else 'false'}"
        f"&expand=dns_names"
    )
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": "Wespennest/1.0"})
        if not r.is_success:
            log.warning("certspotter non-200 for %s: %s", domain, r.status_code)
            return []
        data = r.json() or []
        out: set[str] = set()
        for cert in data:
            for name in cert.get("dns_names") or []:
                n = (name or "").strip().lower().lstrip("*.")
                if n:
                    out.add(n)
        return sorted(out)
    except (httpx.HTTPError, ValueError) as e:
        log.warning("certspotter error for %s: %s", domain, e)
        return []


async def _crtsh_query(q: str, timeout: float = 30.0) -> list[dict]:
    """Hit crt.sh JSON API as a fallback when Certspotter is empty.
    crt.sh frequently returns 502 so callers should not depend on it."""
    url = f"https://crt.sh/?q={quote(q)}&output=json"
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": "Wespennest/1.0"})
        if not r.is_success:
            log.warning("crt.sh non-200 for q=%r: %s", q, r.status_code)
            return []
        return r.json() or []
    except (httpx.HTTPError, ValueError) as e:
        log.warning("crt.sh error for q=%r: %s", q, e)
        return []


_INFRA_LABELS = {
    "www", "mail", "smtp", "imap", "pop", "webmail", "autodiscover",
    "lyncdiscover", "sip", "ftp", "owa", "vpn", "remote", "portal",
    "sso", "auth", "monitoring", "status", "admin", "cpanel", "plesk",
    "ns1", "ns2", "ns3", "mx", "mx1", "mx2", "test", "dev", "staging",
    "exchange", "outlook", "acme", "_acme-challenge", "selector1",
    "selector2", "k1", "default", "atlassian", "office", "365",
    "lyncdiscover", "lync", "skype", "teams",
}


async def discover_crtsh_subdomains(
    msp_apex: str, max_results: int = 200,
) -> list[CustomerCandidate]:
    """Find subdomains under <msp_apex> via Certificate Transparency logs.

    Uses Certspotter as the primary source (reliable JSON API) and falls
    back to crt.sh when Certspotter returns nothing. A common MSP pattern
    is to give each customer a portal/SSO subdomain like
    'klantbedrijf.<msp>.nl' or 'klantbedrijf.portal.<msp>.nl', so the
    leftmost label often hints at the customer name.
    """
    # 1) Try Certspotter (preferred)
    names = await _certspotter_dns_names(msp_apex, include_subdomains=True)
    out: list[CustomerCandidate] = []
    seen_labels: set[str] = set()

    def consider(entry: str, source_tag: str) -> None:
        if len(out) >= max_results:
            return
        entry = entry.strip().lower().lstrip("*.")
        if not entry or entry == msp_apex or _is_boring(entry):
            return
        if not entry.endswith(f".{msp_apex}"):
            return
        # Strip trailing .<msp_apex> to keep the customer-hint subdomain
        customer_label = entry[: -(len(msp_apex) + 1)]
        # Strip any further .portal or .sso interior labels for dedup keys,
        # but keep the full hostname for display.
        first_label = customer_label.split(".")[0]
        if first_label in _INFRA_LABELS:
            return
        if customer_label in seen_labels:
            return
        seen_labels.add(customer_label)
        out.append(CustomerCandidate(
            domain=entry,
            method="crtsh_subdomains",
            evidence=f"{source_tag}: cert SAN for {entry}",
            confidence=55,
        ))

    for name in names:
        consider(name, "Certspotter")
        if len(out) >= max_results:
            return out

    # 2) Fallback to crt.sh only if we got nothing
    if not out:
        rows = await _crtsh_query(f"%.{msp_apex}")
        for row in rows[: max_results * 5]:
            for entry in (row.get("name_value") or "").split("\n"):
                consider(entry, "crt.sh")
                if len(out) >= max_results:
                    return out
    return out


async def discover_crtsh_san(
    msp_apex: str, max_results: int = 200,
) -> list[CustomerCandidate]:
    """Find apex-level customer domains via CT logs.

    Looks at every cert that mentions the MSP somewhere, and harvests
    the *other* domain apexes appearing on those certs. Lower confidence
    than the subdomain method because shared certs are noisier.
    """
    # Pull every cert for the MSP apex (without subdomain expansion)
    # and unpack their SAN lists.
    names = await _certspotter_dns_names(msp_apex, include_subdomains=False)
    seen: set[str] = set()
    out: list[CustomerCandidate] = []
    for entry in names:
        apex = _extract_apex(entry)
        if apex is None or apex == msp_apex or _is_boring(apex):
            continue
        tld = "." + apex.rsplit(".", 1)[-1]
        if tld not in _NL_PRIORITY_TLDS:
            continue
        if apex in seen:
            continue
        seen.add(apex)
        out.append(CustomerCandidate(
            domain=apex, method="crtsh_san",
            evidence=f"Shared CT cert with {msp_apex}",
            confidence=35,
        ))
        if len(out) >= max_results:
            return out
    return out


# ---------------------------------------------------------------------
# DNS-based methods (slower; require a seed list to scan)
# ---------------------------------------------------------------------


async def _resolve_record(domain: str, rtype: str) -> list[str]:
    """Thin async wrapper around dnspython. Returns empty list on errors."""
    try:
        import dns.asyncresolver  # type: ignore[import-untyped]
    except ImportError:
        # dnspython not installed in this environment yet -- the caller
        # gracefully falls back. We log once.
        log.warning("dnspython not installed; DNS-based discovery disabled")
        return []
    try:
        answer = await dns.asyncresolver.resolve(domain, rtype, lifetime=5.0)
        return [str(r).strip().strip('"').lower() for r in answer]
    except Exception:  # noqa: BLE001  (DNS lib raises many subtypes)
        return []


async def discover_mx_pointing_to_msp(
    msp_apex: str, candidate_domains: Iterable[str], max_results: int = 200,
) -> list[CustomerCandidate]:
    """Of the candidate domains, which have MX records pointing at the MSP?"""
    out: list[CustomerCandidate] = []
    sem = asyncio.Semaphore(10)

    async def check(domain: str) -> None:
        if len(out) >= max_results:
            return
        async with sem:
            records = await _resolve_record(domain, "MX")
        for rec in records:
            # 'priority mx.host.' format
            mx_host = rec.split()[-1].rstrip(".") if rec else ""
            if msp_apex in mx_host:
                out.append(CustomerCandidate(
                    domain=domain,
                    method="mx_lookup",
                    evidence=f"MX -> {mx_host}",
                    confidence=85,
                ))
                return

    await asyncio.gather(*(check(d) for d in candidate_domains))
    return out


async def discover_spf_including_msp(
    msp_apex: str, candidate_domains: Iterable[str], max_results: int = 200,
) -> list[CustomerCandidate]:
    """Of the candidate domains, which have SPF that includes the MSP?"""
    out: list[CustomerCandidate] = []
    sem = asyncio.Semaphore(10)

    async def check(domain: str) -> None:
        if len(out) >= max_results:
            return
        async with sem:
            records = await _resolve_record(domain, "TXT")
        for rec in records:
            if not rec.startswith("v=spf"):
                continue
            if msp_apex in rec:
                out.append(CustomerCandidate(
                    domain=domain,
                    method="spf_include",
                    evidence=f"SPF includes {msp_apex}",
                    confidence=80,
                ))
                return

    await asyncio.gather(*(check(d) for d in candidate_domains))
    return out


# ---------------------------------------------------------------------
# Reseller-substring -- cheap heuristic for white-label MSPs whose
# customers literally put the MSP name in their domain
# ---------------------------------------------------------------------


async def discover_reseller_substring(
    msp_apex: str, candidate_domains: Iterable[str], max_results: int = 200,
) -> list[CustomerCandidate]:
    msp_label = msp_apex.split(".")[0].lower()
    if len(msp_label) < 5:
        return []  # too short, noisy
    out: list[CustomerCandidate] = []
    for d in candidate_domains:
        if msp_label in d.lower() and d != msp_apex:
            out.append(CustomerCandidate(
                domain=d, method="reseller_substring",
                evidence=f"{msp_label!r} appears in {d}",
                confidence=40,
            ))
            if len(out) >= max_results:
                break
    return out


# ---------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------


async def run_customer_discovery(
    *,
    msp_apex: str,
    methods: list[str],
    candidate_domains: Iterable[str] | None = None,
    max_per_method: int = 100,
    # Context for AI-powered methods (website crawl, press archive,
    # LinkedIn official). When omitted, those methods are skipped.
    db: "AsyncSession | None" = None,
    org_id: "UUID | None" = None,
    msp_name: str | None = None,
    msp_website: str | None = None,
) -> list[CustomerCandidate]:
    """Run all enabled methods in parallel and return a merged candidate list.

    Method matrix:
      crtsh_subdomains, crtsh_san     -- CT logs (no extra context needed)
      mx_lookup, spf_include,
      reseller_substring              -- DNS (need candidate_domains)
      msp_website_crawl,
      msp_press_archive,
      msp_linkedin_official           -- AI-powered (need db + org_id +
                                         msp_name; website method also
                                         needs msp_website)
    """
    tasks: list[asyncio.Task[list[CustomerCandidate]]] = []
    if "crtsh_subdomains" in methods:
        tasks.append(asyncio.create_task(
            discover_crtsh_subdomains(msp_apex, max_results=max_per_method),
        ))
    if "crtsh_san" in methods:
        tasks.append(asyncio.create_task(
            discover_crtsh_san(msp_apex, max_results=max_per_method),
        ))
    cands = list(candidate_domains or [])
    if cands:
        if "mx_lookup" in methods:
            tasks.append(asyncio.create_task(
                discover_mx_pointing_to_msp(msp_apex, cands, max_results=max_per_method),
            ))
        if "spf_include" in methods:
            tasks.append(asyncio.create_task(
                discover_spf_including_msp(msp_apex, cands, max_results=max_per_method),
            ))
        if "reseller_substring" in methods:
            tasks.append(asyncio.create_task(
                discover_reseller_substring(msp_apex, cands, max_results=max_per_method),
            ))

    # AI-powered methods -- only run when we have db + org_id + msp_name
    if db is not None and org_id is not None and msp_name:
        if "msp_website_crawl" in methods and msp_website:
            tasks.append(asyncio.create_task(_run_website_crawl(
                db, org_id, msp_name, msp_website, max_per_method,
            )))
        if "msp_press_archive" in methods:
            tasks.append(asyncio.create_task(_run_press_archive(
                db, org_id, msp_name, max_per_method,
            )))
        if "msp_linkedin_official" in methods:
            tasks.append(asyncio.create_task(_run_linkedin_official(
                db, org_id, msp_name, msp_website, max_per_method,
            )))

    if not tasks:
        return []
    results: list[CustomerCandidate] = []
    for task in await asyncio.gather(*tasks, return_exceptions=True):
        if isinstance(task, Exception):
            log.warning("discovery task failed: %s", task)
            continue
        results.extend(task)

    # Deduplicate -- same domain across multiple methods keeps the highest
    # confidence.
    best: dict[str, CustomerCandidate] = {}
    for c in results:
        existing = best.get(c.domain)
        if existing is None or c.confidence > existing.confidence:
            best[c.domain] = c
    return sorted(best.values(), key=lambda c: -c.confidence)


# ---------------------------------------------------------------------
# Adapters around the AI-powered methods so the orchestrator gets
# uniform CustomerCandidate output
# ---------------------------------------------------------------------


async def _run_website_crawl(
    db, org_id, msp_name: str, msp_website: str, max_results: int,
) -> list[CustomerCandidate]:
    from salespilot.integrations.msp_intel.website_crawler import (
        crawl_msp_website,
    )
    try:
        hits = await crawl_msp_website(
            db=db, org_id=org_id, msp_name=msp_name,
            msp_website=msp_website, max_results=max_results,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("website crawl failed: %s", e)
        return []
    out: list[CustomerCandidate] = []
    for h in hits:
        # Use the guessed domain when present; else use a synthetic
        # "company:<name>" pseudo-domain so the UI can still display +
        # save it. The user can fix the real domain later.
        domain = h.domain or f"company:{h.name.lower().replace(' ', '-')[:50]}"
        out.append(CustomerCandidate(
            domain=domain,
            method="msp_website_crawl",
            evidence=f"Genoemd op {h.source_url}",
            confidence=h.confidence,
        ))
    return out


async def _run_press_archive(
    db, org_id, msp_name: str, max_results: int,
) -> list[CustomerCandidate]:
    from salespilot.integrations.msp_intel.press_archive import (
        crawl_msp_press_archive,
    )
    try:
        hits = await crawl_msp_press_archive(
            db=db, org_id=org_id, msp_name=msp_name, max_results=max_results,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("press archive failed: %s", e)
        return []
    out: list[CustomerCandidate] = []
    for h in hits:
        # Press articles rarely give us a clean domain; use a slug guess
        slug = (h.name or "").lower()
        # Same simple slug logic as website crawler
        import re as _re
        slug = _re.sub(r"\b(b\.?v\.?|n\.?v\.?|holding|group|nederland|bv|nv)\b\.?", "", slug)
        slug = _re.sub(r"[^a-z0-9]+", "", slug)
        domain = f"{slug}.nl" if 3 <= len(slug) <= 40 else f"company:{slug[:50]}"
        out.append(CustomerCandidate(
            domain=domain,
            method="msp_press_archive",
            evidence=(
                f"Genoemd in {h.source_title or 'persbericht'}: "
                f"{(h.evidence_quote or '')[:160]}"
            ),
            confidence=h.confidence,
        ))
    return out


async def _run_linkedin_official(
    db, org_id, msp_name: str, msp_website: str | None, max_results: int,
) -> list[CustomerCandidate]:
    from salespilot.integrations.msp_intel.linkedin_official import (
        crawl_msp_linkedin_official,
    )
    try:
        hits = await crawl_msp_linkedin_official(
            db=db, org_id=org_id, msp_name=msp_name,
            msp_website=msp_website, max_results=max_results,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("linkedin official failed: %s", e)
        return []
    out: list[CustomerCandidate] = []
    for h in hits:
        out.append(CustomerCandidate(
            domain=f"linkedin:{h.name.lower().replace(' ', '-')[:50]}",
            method="msp_linkedin_official",
            evidence=f"LinkedIn post: {(h.evidence_quote or '')[:160]}",
            confidence=h.confidence,
        ))
    return out
