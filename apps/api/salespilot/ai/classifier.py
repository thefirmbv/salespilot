"""Provider-agnostic AI classifier helper.

Wespennest's overname-monitor and future features (callscript generation,
LinkedIn AI content) need a small "classify or summarise this text" call.
Both OpenAI and Anthropic offer that; this module picks one based on the
org's preference and falls through gracefully.

Why not just one provider:
  * IT-gemak already has an OpenAI account with no per-call credits to
    track separately, so OpenAI is preferred when configured.
  * Anthropic stays as the alternative for richer reasoning tasks.
  * The 'auto' default prefers OpenAI when both are configured.

Usage:
    from salespilot.ai.classifier import classify_with_ai

    result = await classify_with_ai(
        db=db,
        org_id=org_id,
        system_prompt="You classify Dutch IT news headlines...",
        user_prompt="Headline: ...\\nIs this an acquisition? Reply yes/no.",
        max_tokens=120,
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from salespilot.models.integrations import Integration


log = logging.getLogger(__name__)


@dataclass
class AIClassifierResult:
    text: str
    provider: str
    model: str


async def _load_providers(
    db: AsyncSession,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str]:
    rows = (
        await db.execute(
            select(Integration).where(
                Integration.kind.in_(["openai", "anthropic", "wespennest"])
            )
        )
    ).scalars().all()

    openai_cfg: dict[str, Any] | None = None
    anthropic_cfg: dict[str, Any] | None = None
    preference = "auto"
    for r in rows:
        cfg = r.config_json or {}
        if r.kind == "wespennest":
            preference = (cfg.get("ai_classifier_source") or "auto").lower()
            if preference not in ("auto", "openai", "anthropic", "off"):
                preference = "auto"
            continue
        if not r.is_enabled:
            continue
        if r.kind == "openai" and cfg.get("api_key"):
            openai_cfg = cfg
        elif r.kind == "anthropic" and cfg.get("api_key"):
            anthropic_cfg = cfg

    return openai_cfg, anthropic_cfg, preference


def _provider_order(preference: str, has_openai: bool, has_anthropic: bool) -> list[str]:
    if preference == "off":
        return []

    if preference == "openai":
        order = ["openai", "anthropic"]
    elif preference == "anthropic":
        order = ["anthropic", "openai"]
    else:
        if has_openai and has_anthropic:
            order = ["openai", "anthropic"]
        elif has_openai:
            order = ["openai"]
        else:
            order = ["anthropic"]

    return [
        p for p in order
        if (p == "openai" and has_openai) or (p == "anthropic" and has_anthropic)
    ]


async def _call_openai(
    cfg: dict[str, Any], *, system_prompt: str, user_prompt: str, max_tokens: int,
) -> str | None:
    api_key = cfg.get("api_key")
    if not api_key:
        return None
    base_url = (cfg.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    model = cfg.get("model") or "gpt-4o-mini"
    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_tokens": max_tokens,
                    "temperature": 0.1,
                },
            )
        if not r.is_success:
            log.warning("OpenAI classifier failed: %s %s", r.status_code, r.text[:300])
            return None
        data = r.json()
        return (data["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:  # noqa: BLE001
        log.warning("OpenAI classifier exception: %s", e)
        return None


async def _call_anthropic(
    cfg: dict[str, Any], *, system_prompt: str, user_prompt: str, max_tokens: int,
) -> str | None:
    api_key = cfg.get("api_key")
    if not api_key:
        return None
    model = cfg.get("model") or "claude-haiku-4-5-20251001"
    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_prompt}],
                    "temperature": 0.1,
                },
            )
        if not r.is_success:
            log.warning("Anthropic classifier failed: %s %s", r.status_code, r.text[:300])
            return None
        data = r.json()
        blocks = data.get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return text.strip() or None
    except Exception as e:  # noqa: BLE001
        log.warning("Anthropic classifier exception: %s", e)
        return None


async def classify_with_ai(
    *,
    db: AsyncSession,
    org_id: UUID,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 200,
) -> AIClassifierResult | None:
    """Run a single classifier call through the org's preferred AI provider."""
    openai_cfg, anthropic_cfg, preference = await _load_providers(db)
    order = _provider_order(preference, openai_cfg is not None, anthropic_cfg is not None)
    if not order:
        return None

    for provider in order:
        if provider == "openai" and openai_cfg is not None:
            text = await _call_openai(
                openai_cfg,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
            )
            if text:
                return AIClassifierResult(
                    text=text, provider="openai",
                    model=openai_cfg.get("model") or "gpt-4o-mini",
                )
        elif provider == "anthropic" and anthropic_cfg is not None:
            text = await _call_anthropic(
                anthropic_cfg,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
            )
            if text:
                return AIClassifierResult(
                    text=text, provider="anthropic",
                    model=anthropic_cfg.get("model") or "claude-haiku-4-5-20251001",
                )
    return None


async def classify_yes_no(
    *,
    db: AsyncSession,
    org_id: UUID,
    system_prompt: str,
    user_prompt: str,
) -> tuple[bool | None, AIClassifierResult | None]:
    """Convenience wrapper for binary yes/no classification."""
    result = await classify_with_ai(
        db=db, org_id=org_id,
        system_prompt=system_prompt, user_prompt=user_prompt,
        max_tokens=8,
    )
    if result is None:
        return None, None
    answer = result.text.lower().strip()
    answer = answer.split()[0].rstrip(".:,;!?") if answer else ""
    if answer in ("yes", "y", "ja", "true", "1"):
        return True, result
    if answer in ("no", "n", "nee", "false", "0"):
        return False, result
    return None, result
