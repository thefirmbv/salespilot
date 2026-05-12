"""AI callscript generation using the Anthropic API.

Inputs:
  - company facts (name, industry, employees, city, country, description)
  - detected mail platform (m365 / google / other / unknown)
  - recent page visits (titles + urls)
  - optional website summary (we can scrape the home page text and pass it
    along so Claude can tailor more sharply)

Output:
  - a Callscript with 4 steps (Opening / Hook / Qualification / Appointment)
  - a context summary used as a tooltip in the UI
  - optional decision-maker hint

If the Anthropic key is missing or the request fails, we fall back to a
template-based script so the UI keeps working — it just won't be as
tailored.
"""

import json
from datetime import UTC, datetime
from typing import Any

import httpx

from salespilot.schemas.integrations import Callscript, CallscriptStep


def _platform_label(mail_platform: str) -> str:
    return {
        "m365": "Microsoft 365",
        "google": "Google Workspace",
        "other": "een eigen mailomgeving",
        "unknown": "een onbekende mailomgeving",
    }.get(mail_platform, "een onbekende mailomgeving")


def _build_prompt(
    *,
    company: dict[str, Any],
    pageviews: list[dict[str, Any]],
    website_summary: str | None,
) -> str:
    pv_lines = "\n".join(
        f"  - {pv.get('page_title') or pv.get('url') or 'page'} ({pv.get('url') or ''})"
        for pv in pageviews[:10]
    ) or "  (geen)"

    return f"""Je bent een ervaren Nederlandse sales rep voor een Managed Services Provider (IT-beheer).
Doel: een koud bel-script schrijven voor de prospect hieronder.

Bedrijf:
  Naam: {company.get('name') or '?'}
  Domein: {company.get('domain') or '?'}
  Branche: {company.get('industry') or '?'}
  Medewerkers: {company.get('employees') or '?'}
  Plaats: {company.get('city') or '?'}, {company.get('country') or 'NL'}
  Beschrijving: {company.get('description') or '?'}
  Detected mailplatform: {_platform_label(company.get('mail_platform', 'unknown'))}

Recent bezochte pagina's op onze website:
{pv_lines}

Website samenvatting (geschraapt door ons systeem):
{website_summary or 'Niet beschikbaar.'}

Onze ICP is 20-60 kantoormedewerkers zonder eigen IT-afdeling.

Geef je antwoord als ÉÉN JSON-object — geen markdown, geen omhulsel, geen toelichting eromheen.
Schema:
{{
  "context_summary": "1 zin met de zakelijke context (wat doen ze, hoe staan ze in de markt)",
  "decision_maker_hint": "1 zin: wie waarschijnlijk de beslisser is (titel of rol)",
  "steps": [
    {{"title": "Opening", "content": "1-2 zinnen openingszin in het Nederlands, persoonlijk"}},
    {{"title": "Hook", "content": "2-3 zinnen op maat gebaseerd op mailplatform + bezochte pagina's + bedrijfsgrootte"}},
    {{"title": "Kwalificatie", "content": "3 korte kwalificatievragen, genummerd"}},
    {{"title": "Afspraak", "content": "Concreet afspraakvoorstel met twee dag-opties"}}
  ]
}}

Belangrijk:
- Schrijf in vlot Nederlands.
- Geen markdown of code-blokken.
- Geen overdreven verkooptaal.
- Concrete, geloofwaardige zinnen die een echte sales rep zou zeggen.
"""


def _fallback(company: dict[str, Any]) -> tuple[list[CallscriptStep], str, str]:
    name = company.get("name", "uw bedrijf")
    platform_label = _platform_label(company.get("mail_platform", "unknown"))
    industry = company.get("industry") or "uw sector"
    employees = company.get("employees")
    size_phrase = f"{employees} medewerkers" if employees else "uw bedrijfsgrootte"

    steps = [
        CallscriptStep(
            title="Opening",
            content=(
                f"Goedemorgen, met [naam] van IT-Gemak — "
                f"kan ik kort de persoon spreken die verantwoordelijk is voor IT bij {name}?"
            ),
        ),
        CallscriptStep(
            title="Hook",
            content=(
                f"Ik zag dat jullie op {platform_label} draaien — solide basis. "
                f"Bij bedrijven in {industry} met {size_phrase} zie ik geregeld dat "
                "device-beheer, backup en security niet centraal geregeld zijn. "
                "Herkent u dat ook?"
            ),
        ),
        CallscriptStep(
            title="Kwalificatie",
            content=(
                "1) Hebben jullie nu een vaste IT-partner? "
                "2) Hoeveel laptops/pc's draaien er totaal? "
                "3) Wat is jullie grootste IT-ergernis van het afgelopen kwartaal?"
            ),
        ),
        CallscriptStep(
            title="Afspraak",
            content=(
                "Ik stel een kennismaking van 30 minuten voor — gratis IT-scan, "
                "online of bij jullie. Schikt donderdag 14:00 of vrijdag 10:00 beter?"
            ),
        ),
    ]
    return steps, f"Geen AI beschikbaar — fallback script op basis van bedrijfsdata.", "Directeur of IT-verantwoordelijke."


async def generate_callscript(
    *,
    api_key: str | None,
    model: str,
    company: dict[str, Any],
    pageviews: list[dict[str, Any]],
    website_summary: str | None = None,
) -> Callscript:
    """Try Anthropic; fall back to template on any error / missing key."""
    generated_at = datetime.now(UTC)

    if not api_key:
        steps, summary, hint = _fallback(company)
        return Callscript(
            company_id=company["id"],
            generated_at=generated_at,
            model="fallback",
            steps=steps,
            context_summary=summary,
            decision_maker_hint=hint,
        )

    prompt = _build_prompt(
        company=company, pageviews=pageviews, website_summary=website_summary
    )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 1500,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        if res.status_code >= 400:
            raise RuntimeError(f"anthropic returned {res.status_code}: {res.text[:300]}")
        body = res.json()
        text = "".join(
            block.get("text", "")
            for block in body.get("content", [])
            if block.get("type") == "text"
        ).strip()
        # Strip ``` fences if the model added them despite instructions.
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
        data = json.loads(text)
        steps = [
            CallscriptStep(title=s["title"], content=s["content"])
            for s in data.get("steps", [])
        ]
        if not steps:
            raise RuntimeError("model returned no steps")
        return Callscript(
            company_id=company["id"],
            generated_at=generated_at,
            model=model,
            steps=steps,
            context_summary=data.get("context_summary", ""),
            website_summary=website_summary,
            decision_maker_hint=data.get("decision_maker_hint"),
        )
    except Exception as e:  # noqa: BLE001
        steps, summary, hint = _fallback(company)
        return Callscript(
            company_id=company["id"],
            generated_at=generated_at,
            model=f"fallback ({type(e).__name__})",
            steps=steps,
            context_summary=summary,
            decision_maker_hint=hint,
        )


async def scrape_website_summary(domain: str | None, max_chars: int = 1800) -> str | None:
    """Best-effort homepage fetch + plain-text extraction.

    We deliberately don't render JS (no headless browser) and don't follow
    redirects beyond one hop. This is a hint for the LLM, not the source
    of truth.
    """
    if not domain:
        return None
    cleaned = domain.strip().lower()
    if not cleaned.startswith(("http://", "https://")):
        cleaned = "https://" + cleaned
    try:
        async with httpx.AsyncClient(
            timeout=8.0, follow_redirects=True, headers={"User-Agent": "SalesPilot/1.0"}
        ) as client:
            res = await client.get(cleaned)
    except Exception:  # noqa: BLE001
        return None
    if res.status_code >= 400:
        return None
    html = res.text or ""
    # Crude text extraction — strip tags. We don't want to ship BeautifulSoup
    # just for this. Anything in <script>/<style> is removed.
    import re

    cleaned_html = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    cleaned_html = re.sub(r"<style.*?</style>", " ", cleaned_html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", cleaned_html)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    return text[:max_chars]
