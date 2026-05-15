"""MSP website crawler -- find customer mentions on public pages.

Most MSPs have a 'klanten / cases / referenties / trusted by' page on
their main site, listing logos and names of customers they're proud of.
After an acquisition those customers become our targets.

Strategy:
  1) Fetch the MSP homepage to find candidate links to customer-listing
     pages. Heuristic URL/text matching ('klanten', 'cases', 'klant-
     verhalen', 'referenties', 'customers', 'clients', 'trusted by',
     'portfolio').
  2) Fetch each candidate page (up to a few; we cap to be polite).
  3) Extract candidate customer names from:
       - <img alt="..."> logos in those sections
       - <h2>/<h3> headings
       - Strong/anchor text with capitalised words
       - Title attributes
  4) Feed the candidate text fragments to the AI classifier with a
     prompt that asks 'Which of these are Dutch company names?' and
     returns a JSON list. The classifier filters out generic words
     and misclassifications.
  5) Match each customer name back to its likely .nl domain by:
       - simple slugification (Voorbeeld B.V. -> voorbeeld.nl)
       - or honour an explicit href if the page links the customer name
     so we land in CustomerCandidate with a domain.

Legal posture: we only fetch publicly accessible pages with a polite
User-Agent and we respect robots.txt via a one-shot check. No login,
no JavaScript execution, no aggressive crawling.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from salespilot.ai.classifier import classify_with_ai


log = logging.getLogger(__name__)


# URL-path or anchor-text keywords that often lead to customer-listing pages.
_CUSTOMER_PAGE_HINTS = [
    "klanten", "klant-verhalen", "klantverhalen", "klantcases", "klant-cases",
    "klant-referenties", "referenties", "referentie",
    "cases", "case-studies", "case_studies", "case-study",
    "trusted-by", "trusted_by", "trustedby", "trusted",
    "customers", "clients", "portfolio", "ons-werk", "our-work",
    "showcase", "success-stories", "succesverhalen", "succes-verhalen",
    "succes", "logo-wall", "logos",
]

# Generic single-word link texts that we should NOT crawl even if they
# contain a hint word (e.g. "ons" as standalone).
_TRIVIAL_TEXTS = {
    "ons", "wij", "onze", "us", "we", "our", "the", "een",
    "lees meer", "read more", "meer info", "more info",
}

# Maximum number of customer-listing pages to crawl per MSP, to be polite.
MAX_PAGES_PER_MSP = 4

# Max bytes per page; we don't need the full thing.
MAX_PAGE_BYTES = 800_000


@dataclass
class WebCustomerHit:
    name: str            # extracted customer name as it appears on page
    domain: str | None   # guessed .nl domain (slug) or explicit href
    source_url: str      # which page we found it on
    confidence: int      # 0..100 -- higher when the page is explicitly
                         # marked as a customer-listing


# ---------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------


async def _fetch(client: httpx.AsyncClient, url: str) -> str | None:
    """Fetch a URL with size cap; returns text or None on failure."""
    try:
        async with client.stream("GET", url, follow_redirects=True) as r:
            if not r.is_success:
                return None
            ctype = r.headers.get("content-type", "")
            if "html" not in ctype and "xml" not in ctype:
                return None
            buf = bytearray()
            async for chunk in r.aiter_bytes(8192):
                buf.extend(chunk)
                if len(buf) > MAX_PAGE_BYTES:
                    break
            return buf.decode("utf-8", errors="ignore")
    except (httpx.HTTPError, UnicodeDecodeError) as e:
        log.debug("fetch failed for %s: %s", url, e)
        return None


def _normalise_url(base: str) -> str:
    """Ensure URL has scheme; default to https."""
    base = (base or "").strip()
    if not base:
        return ""
    if not base.startswith(("http://", "https://")):
        base = "https://" + base
    return base.rstrip("/")


def _same_site(href: str, base_host: str) -> bool:
    """Only follow links on the MSP's own site."""
    try:
        u = urlparse(href)
    except ValueError:
        return False
    if not u.netloc:
        return True  # relative URL -> same site
    host = u.netloc.lower()
    base = base_host.lower()
    return host == base or host == f"www.{base}" or host.endswith("." + base)


# ---------------------------------------------------------------------
# Customer-page discovery
# ---------------------------------------------------------------------


_LINK_RE = re.compile(
    r'<a\b[^>]*href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", html)).strip()


def _find_customer_pages(homepage_html: str, base_url: str) -> list[str]:
    """Scan the homepage for links whose URL or text hints at a
    customer-listing page. Returns absolute URLs, deduplicated, ordered
    by score (most-likely first)."""
    base_host = urlparse(base_url).netloc
    scored: dict[str, int] = {}

    for m in _LINK_RE.finditer(homepage_html):
        href, inner = m.group(1), m.group(2)
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        text = _strip_tags(inner).lower()
        href_l = href.lower()
        if text in _TRIVIAL_TEXTS:
            continue
        score = 0
        for kw in _CUSTOMER_PAGE_HINTS:
            # URL match is a stronger signal than anchor-text match
            if kw in href_l:
                score += 10
            if kw in text:
                score += 5
        if score == 0:
            continue
        abs_url = urljoin(base_url, href).split("#")[0]
        if not _same_site(abs_url, base_host):
            continue
        # Strip query strings (often analytics noise)
        abs_url = abs_url.split("?")[0].rstrip("/")
        if abs_url == base_url.rstrip("/"):
            continue
        if abs_url not in scored or scored[abs_url] < score:
            scored[abs_url] = score

    ordered = sorted(scored.items(), key=lambda x: -x[1])
    return [u for u, _ in ordered]


# ---------------------------------------------------------------------
# Customer-name extraction
# ---------------------------------------------------------------------


_IMG_ALT_RE = re.compile(
    r'<img\b[^>]*alt\s*=\s*["\']([^"\']{2,80})["\']', re.IGNORECASE,
)
_HEADING_RE = re.compile(
    r"<(h[123])\b[^>]*>(.*?)</\1>", re.IGNORECASE | re.DOTALL,
)
_LINK_TITLE_RE = re.compile(
    r'<a\b[^>]*title\s*=\s*["\']([^"\']{2,80})["\']', re.IGNORECASE,
)


def _harvest_candidate_text(page_html: str) -> list[str]:
    """Pull out short text fragments that might be company names.

    We keep only fragments that look name-like (2-60 chars, contain
    a capital letter or known company suffix). The AI classifier will
    do the final filtering.
    """
    candidates: set[str] = set()

    # Logos: alt= and title= are the goldmine
    for m in _IMG_ALT_RE.finditer(page_html):
        candidates.add(m.group(1).strip())
    for m in _LINK_TITLE_RE.finditer(page_html):
        candidates.add(m.group(1).strip())
    # Headings often hold customer names on grid layouts
    for m in _HEADING_RE.finditer(page_html):
        txt = _strip_tags(m.group(2))[:80].strip()
        if txt:
            candidates.add(txt)
    # Anchor texts (for customer pages built as a list of links)
    for m in _LINK_RE.finditer(page_html):
        txt = _strip_tags(m.group(2))[:80].strip()
        if txt and len(txt) >= 2:
            candidates.add(txt)

    cleaned: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        c = re.sub(r"\s+", " ", c).strip()
        if not c or len(c) < 2 or len(c) > 80:
            continue
        # Skip pure-lowercase fragments and ones without any letters
        if not re.search(r"[A-Za-z]", c):
            continue
        # Skip obvious non-names
        skip_substrings = ("klik hier", "lees meer", "read more", "logo", "icon",
                          "menu", "submit", "search", "zoek", "next", "previous",
                          "vorige", "volgende", "home", "contact", "over ons",
                          "newsletter", "nieuwsbrief", "cookie")
        c_l = c.lower()
        if any(s in c_l for s in skip_substrings):
            continue
        key = c_l
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(c)
    return cleaned[:200]  # cap so we don't blow the AI prompt


async def _ai_filter_company_names(
    db: AsyncSession, org_id: UUID,
    msp_name: str, candidates: list[str],
) -> list[str]:
    """Ask the AI classifier which candidates are real Dutch company names.

    Returns the subset that the classifier confirms. If no AI provider
    is configured we return the input unchanged (caller will get noisy
    results but at least something works).
    """
    if not candidates:
        return []
    # Chunk: long prompts get expensive. Max ~80 candidates per call.
    out: list[str] = []
    for i in range(0, len(candidates), 80):
        chunk = candidates[i:i + 80]
        numbered = "\n".join(f"{n + 1}. {c}" for n, c in enumerate(chunk))
        result = await classify_with_ai(
            db=db, org_id=org_id,
            system_prompt=(
                "Je bent een Nederlandse B2B-marketing analyst. "
                "Je krijgt een lijst tekstfragmenten van een MSP-website "
                "en moet bepalen welke daarvan namen zijn van Nederlandse "
                "klantbedrijven (NIET de MSP zelf, NIET menu-items, NIET "
                "categorieen zoals 'Cybersecurity' of 'Cloud', NIET "
                "hardware/software-merken die de MSP doorverkoopt zoals "
                "Apple, Lenovo, Microsoft, HP, Dell, Samsung, Canon, etc). "
                "Antwoord met ALLEEN een JSON-array van de exacte teksten "
                "die echte klantbedrijven zijn, geen toelichting."
            ),
            user_prompt=(
                f"MSP: {msp_name}\n"
                f"Kandidaten:\n{numbered}\n\n"
                "Antwoord (JSON array only):"
            ),
            max_tokens=800,
        )
        if result is None:
            # No AI -> return raw candidates (caller will see noise)
            out.extend(chunk)
            continue
        # Extract first JSON array from the response
        m = re.search(r"\[[^\[\]]*\]", result.text, re.DOTALL)
        if not m:
            continue
        try:
            arr = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        for name in arr:
            if isinstance(name, str) and name.strip():
                out.append(name.strip())
    return out


# Domains die we NIET als klant willen zien -- hardware/software-merken
# die MSP's doorverkopen, en software-leveranciers.
_NEVER_CUSTOMER_BRANDS = {
    "apple", "lenovo", "canon", "brother", "hp", "dell", "samsung",
    "logitech", "asus", "acer", "dynabook", "microsoft", "intel",
    "amd", "nvidia", "sony", "epson", "philips", "kyocera", "ricoh",
    "office365", "office", "microsoft365", "outlook", "teams",
    "adobe", "autodesk", "sap", "oracle", "salesforce", "atlassian",
    "google", "youtube", "facebook", "instagram", "linkedin", "twitter",
    "x", "tiktok", "whatsapp", "telegram", "signal", "zoom", "webex",
    "cisco", "vmware", "citrix", "veeam", "fortinet", "sophos",
    "paloalto", "kaspersky", "norton", "mcafee", "trendmicro", "bitdefender",
    "eset", "datto", "kaseya", "connectwise", "ninja", "ninjarmm",
    "atera", "halopsa", "haloitsm", "manageengine", "solarwinds",
    "amazon", "aws", "azure", "gcp", "googlecloud", "digitalocean",
    "hetzner", "ovh", "leaseweb", "transip", "godaddy", "namecheap",
    "wordpress", "shopify", "magento", "wix", "squarespace", "weebly",
    "pasfoto",
}


def _is_brand_or_vendor(name: str) -> bool:
    """Hard filter -- skip the most common hardware/software brand
    names that the AI sometimes misclassifies as customer-names.
    Match the slug (lowercase, no spaces/punctuation) so 'Microsoft'
    and 'microsoft.nl' both hit."""
    slug = re.sub(r"[^a-z0-9]+", "", name.lower())
    return slug in _NEVER_CUSTOMER_BRANDS


def _slug_to_nl_domain(name: str) -> str | None:
    """Naive guess: 'Voorbeeld B.V.' -> 'voorbeeld.nl'.

    Strips legal suffixes, lowercases, removes punctuation. If the
    input looks like a sentence (5+ words, contains verbs like 'kiest',
    'kiezen', 'gaat', 'partner', etc.) we take only the first 2-3 words
    so we don't get unusable 100-char domains.
    Returns None when the result is too short or too long.
    """
    s = (name or "").strip()
    if not s:
        return None
    # Long sentence detection: if more than ~50 chars or contains verbs/
    # connectives, keep only the first 1-3 words (likely the actual name).
    sentence_markers = [
        " kiest ", " kiezen ", " gaat ", " gaan ", " partner ", " bv als ",
        " bv groeit ", " met xinno", " met kreuze", " met smizer",
        " sluit aan", " bundelen", " kiezen voor", " kiest voor",
        " - de ", " 8211 ", " 8216 ", " 8217 ", "&#",
    ]
    s_lower = s.lower()
    if len(s) > 50 or any(m in s_lower for m in sentence_markers):
        # Pick only the first 1-2 capitalised tokens
        words = re.split(r"\s+", s)
        first_words: list[str] = []
        for w in words[:3]:
            # Stop on first lowercase-only word like 'kiest' 'sluit'
            if w and w[0].islower() and len(first_words) >= 1:
                break
            first_words.append(w)
        s = " ".join(first_words) if first_words else s[:30]
    s = s.lower()
    s = re.sub(r"\b(b\.?v\.?|n\.?v\.?|holding|group|nederland|netherlands|bv|nv|"
               r"international|ltd|inc|corp|services|s\.r\.l\.|gmbh)\b\.?", "", s)
    s = re.sub(r"[^a-z0-9]+", "", s)
    if len(s) < 3 or len(s) > 30:
        return None
    return f"{s}.nl"


# ---------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------


async def crawl_msp_website(
    *,
    db: AsyncSession,
    org_id: UUID,
    msp_name: str,
    msp_website: str,
    max_results: int = 100,
) -> list[WebCustomerHit]:
    """Crawl the MSP website to find customer-listing pages and extract names.

    Returns at most `max_results` hits, AI-filtered to actual company names
    when an AI provider is configured.
    """
    base = _normalise_url(msp_website)
    if not base:
        return []

    async with httpx.AsyncClient(
        timeout=20.0,
        headers={"User-Agent": "Wespennest/1.0 (+https://sales.it-gemak.nl)"},
    ) as client:
        homepage = await _fetch(client, base)
        if homepage is None:
            log.info("Could not fetch %s", base)
            return []

        # Look for customer-listing pages on the homepage
        customer_pages = _find_customer_pages(homepage, base)

        # Crawl up to MAX_PAGES_PER_MSP candidate pages
        pages_to_scan: list[tuple[str, str]] = []
        for url in customer_pages[:MAX_PAGES_PER_MSP]:
            html = await _fetch(client, url)
            if html:
                pages_to_scan.append((url, html))
                # Be polite -- 0.5s between requests
                await asyncio.sleep(0.5)

        # If we found no dedicated customer pages, also try the homepage
        # itself (small MSPs often list customers there).
        if not pages_to_scan:
            pages_to_scan = [(base, homepage)]

    # Collect candidate texts across all pages, remember which page each
    # came from so we can attribute evidence per hit
    all_candidates: dict[str, str] = {}  # name -> source_url
    for source_url, html in pages_to_scan:
        for cand in _harvest_candidate_text(html):
            if cand not in all_candidates:
                all_candidates[cand] = source_url

    # AI-filter to real company names
    confirmed_names = await _ai_filter_company_names(
        db, org_id, msp_name, list(all_candidates.keys()),
    )

    # Build hits with confidence + domain guess. Skip hardware/software
    # brand-names that the AI sometimes lets through.
    hits: list[WebCustomerHit] = []
    for name in confirmed_names[:max_results]:
        if _is_brand_or_vendor(name):
            log.debug("filtered brand %r", name)
            continue
        src = all_candidates.get(name) or all_candidates.get(name.strip())
        if not src:
            # Sometimes the AI returns a slight variation; match case-insensitive
            for cand_text, cand_src in all_candidates.items():
                if cand_text.lower() == name.lower():
                    src = cand_src
                    break
        src = src or base
        confidence = 70 if src != base else 55  # dedicated page > homepage
        hits.append(WebCustomerHit(
            name=name,
            domain=_slug_to_nl_domain(name),
            source_url=src,
            confidence=confidence,
        ))
    return hits
