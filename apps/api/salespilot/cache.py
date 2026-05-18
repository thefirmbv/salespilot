"""Redis cache helpers voor langzame externe-API queries.

We gebruiken EXPLICIETE calls i.p.v. decorator-pattern omdat FastAPI's
dependency-injection door functools.wraps heenkijkt en de wrapper-laag
kan overslaan.

Usage:

    async def my_handler(auth: CurrentAuth, db: Db, months: int = 12):
        cache_key = make_cache_key("financieel:recurring", auth.org_id, {"months": months})
        cached = await cache_get(cache_key, model=RecurringSummary)
        if cached:
            return cached
        result = await _compute(...)  # echte werk
        await cache_set(cache_key, result, ttl=300)
        return result
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Type, TypeVar

import redis.asyncio as aioredis
from pydantic import BaseModel

from salespilot.config import get_settings


logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

_pool: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _pool
    if _pool is None:
        s = get_settings()
        _pool = aioredis.Redis(
            host=s.redis_host, port=s.redis_port,
            password=s.redis_password.get_secret_value() if s.redis_password else None,
            decode_responses=True,
            socket_timeout=2.0, socket_connect_timeout=2.0,
        )
    return _pool


def make_cache_key(prefix: str, scope: Any, params: dict[str, Any]) -> str:
    """Bouw deterministische cache-key uit prefix + scope (bv. org_id) + params."""
    canon = json.dumps(params, sort_keys=True, default=str)
    h = hashlib.sha1(canon.encode()).hexdigest()[:12]
    return f"{prefix}:{scope}:{h}"


async def cache_get(key: str, model: Type[T] | None = None) -> Any:
    """Lees cached value. Returnt:
       - model-instance als 'model' gegeven en cache hit
       - raw dict/list als model=None en cache hit
       - None bij cache miss / error
    """
    try:
        r = _get_redis()
        raw = await r.get(key)
        if raw is None:
            return None
        logger.info(f"cache HIT {key}")
        if model is not None:
            return model.model_validate_json(raw)
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"cache GET failed for {key}: {e}")
        return None


async def cache_set(key: str, value: Any, ttl: int = 300) -> None:
    """Schrijf naar cache. Accepteert pydantic models OF JSON-serialiseerbare dicts/lists."""
    try:
        r = _get_redis()
        if hasattr(value, "model_dump_json"):
            payload = value.model_dump_json()
        elif isinstance(value, list) and value and hasattr(value[0], "model_dump_json"):
            payload = json.dumps([json.loads(v.model_dump_json()) for v in value])
        else:
            payload = json.dumps(value, default=str)
        await r.set(key, payload, ex=ttl)
        logger.info(f"cache SET {key} (ttl={ttl}s)")
    except Exception as e:
        logger.warning(f"cache SET failed for {key}: {e}")


async def cache_get_list(key: str, item_model: Type[T]) -> list[T] | None:
    """Lees gecached lijst van pydantic models."""
    try:
        r = _get_redis()
        raw = await r.get(key)
        if raw is None:
            return None
        logger.info(f"cache HIT {key} (list)")
        items = json.loads(raw)
        return [item_model.model_validate(i) for i in items]
    except Exception as e:
        logger.warning(f"cache GET (list) failed for {key}: {e}")
        return None


async def invalidate_prefix(prefix: str) -> int:
    """Wis alle keys met deze prefix. Returnt aantal verwijderd."""
    r = _get_redis()
    deleted = 0
    async for key in r.scan_iter(match=f"{prefix}:*", count=200):
        await r.delete(key)
        deleted += 1
    return deleted
