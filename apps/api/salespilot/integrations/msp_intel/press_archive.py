"""Press-archive extractor for customer mentions in acquisition articles.

When the overname-monitor finds 'Y neemt X over' in Computable or Dutch
IT Channel, the article body often lists customers of X explicitly:
"Met deze overname krijgt Y er klanten als Albert Heijn, Gemeente
Amsterdam, en Politie Nederland bij." -- exactly what we want.

Strategy:
  1) For each wn_acquisition_signal where the MSP we're hunting is
     either acquired_party or acquiring_party, fetch the full article.
  2) Pass the article text to the AI classifier with a prompt that
     extracts a JSON list of customer organisations mentioned.
  3) Return as CustomerCandidate-shaped rows.

Legal posture: we fetch one-shot, public press articles with a polite
User-Agent. No login, no aggressive crawling.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from salespilot.ai.classifier import classify_with_ai
from salespilot.models.wespennest import WnAcquisitionSignal


log = logging.getLogger(__name__)


MAX_ARTICLE_BYTES = 600_000
MAX_ARTICLES_PER_MSP = 8


@dataclass
class PressCustomerHit:
    name: str
    source_url: str   # article URL that mentioned this customer
    source_title: str
    evidence_quote: str | None
    confidence: int


_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


async def _fetch_article(client: httpx.AsyncClient, url: str) -> str | None:
    """Fetch an article and strip to plain text (good enough for AI)."""
    try:
        async with client.stream("GET", url, follow_redirects=True) as r:
            if not r.is_success:
                return None
            buf = bytearray()
            async for chunk in r.aiter_bytes(8192):
                buf.extend(chunk)
                if len(buf) > MAX_ARTICLE_BYTES:
                    break
            html = buf.decode("utf-8", errors="ignore")
    except httpx.HTTPError as e:
        log.debug("press fetch failed %s: %s", url, e)
        return None
    # Strip scripts/styles + tags
    html = re.sub(r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>", "", html, flags=re.I | re.S)
    html = re.sub(r"<style\b[^<]*(?:(?!</style>)<[^<]*)*</style>", "", html, flags=re.I | re.S)
    text = _WHITESPACE_RE.sub(" ", _TAG_RE.sub(" ", html)).strip()
    return text[:30_000]  # cap for AI cost


def _find_relevant_articles(
    msp_name: str,
    signals: list[WnAcquisitionSignal],
) -> list[WnAcquisitionSignal]:
    """Pick acquisition signals where this MSP is involved.

    The wn_acquisition_signals table stores the article title + excerpt
    but the AI-classified acquired_party/acquiring_party fields are not
    persisted as columns yet. We match on title + excerpt for now;
    later we can add those columns and broaden the match.
    """
    needle = msp_name.lower().strip()
    relevant: list[WnAcquisitionSignal] = []
    for s in signals:
        title = (s.title or "").lower()
        excerpt = (s.excerpt or "").lower()
        if needle in title or needle in excerpt:
            relevant.append(s)
    return relevant[:MAX_ARTICLES_PER_MSP]


async def _ai_extract_customers(
    db: AsyncSession, org_id: UUID,
    msp_name: str, article_text: str, source_url: str, source_title: str,
) -> list[PressCustomerHit]:
    """Ask the AI classifier which customer companies are mentioned in the
    article body. Returns a list of {name, evidence_quote}."""
    if not article_text or len(article_text) < 200:
        return []
    result = await classify_with_ai(
        db=db, org_id=org_id,
        system_prompt=(
            "Je analyseert een Nederlands persbericht over een IT-overname. "
            "Identificeer organisaties die expliciet als KLANT van de "
            "overgenomen partij worden genoemd -- NIET de overnemer, NIET "
            "de overgenomen partij zelf, NIET investeerders/banken, NIET "
            "industrie-categorieën. "
            "Geef ALLEEN een JSON-array terug. Elk element is een object "
            "met 'name' en 'quote' (de zin uit het artikel waarin deze "
            "klant genoemd wordt). Geen toelichting voor of na de JSON."
        ),
        user_prompt=(
            f"Overgenomen MSP: {msp_name}\n"
            f"Artikel:\n{article_text[:8000]}\n\n"
            "Antwoord (JSON array only, leeg [] als geen klanten genoemd):"
        ),
        max_tokens=800,
    )
    if result is None:
        return []
    m = re.search(r"\[.*\]", result.text, re.DOTALL)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    hits: list[PressCustomerHit] = []
    for item in arr:
        if not isinstance(item, dict):
            continue
        name = (item.get("name") or "").strip()
        quote = (item.get("quote") or "").strip()[:300]
        if not name or len(name) < 2 or len(name) > 100:
            continue
        hits.append(PressCustomerHit(
            name=name,
            source_url=source_url,
            source_title=source_title,
            evidence_quote=quote or None,
            confidence=75,  # press is high-trust when AI confirms
        ))
    return hits


async def crawl_msp_press_archive(
    *,
    db: AsyncSession,
    org_id: UUID,
    msp_name: str,
    max_results: int = 100,
) -> list[PressCustomerHit]:
    """Mine acquisition-signal articles for customer mentions.

    Reads wn_acquisition_signals where the MSP name appears in title or
    parties, fetches the full article for each, asks the AI to extract
    customer mentions. Returns a deduplicated list of hits.
    """
    # Only signals where our MSP is mentioned
    all_signals = (
        await db.execute(
            select(WnAcquisitionSignal).where(
                WnAcquisitionSignal.org_id == org_id,
            )
        )
    ).scalars().all()
    relevant = _find_relevant_articles(msp_name, all_signals)
    if not relevant:
        return []

    async with httpx.AsyncClient(
        timeout=25.0,
        headers={"User-Agent": "Wespennest/1.0 (+https://sales.it-gemak.nl)"},
    ) as client:
        # Be polite: fetch sequentially with a small delay between articles
        all_hits: dict[str, PressCustomerHit] = {}
        for sig in relevant:
            if not sig.source_url:
                continue
            article_text = await _fetch_article(client, sig.source_url)
            if not article_text:
                continue
            hits = await _ai_extract_customers(
                db, org_id, msp_name, article_text,
                sig.source_url, sig.title or "",
            )
            for h in hits:
                key = h.name.lower().strip()
                if key not in all_hits:
                    all_hits[key] = h
                if len(all_hits) >= max_results:
                    break
            await asyncio.sleep(0.7)  # polite delay between articles
            if len(all_hits) >= max_results:
                break

    return list(all_hits.values())
