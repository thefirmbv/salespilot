"""Database session management with multi-tenant Row Level Security.

Pattern: every request that operates within an organization sets the Postgres
session variable `app.current_org_id` *inside the same transaction* as the
query. RLS policies on every tenant-scoped table compare row.org_id against
this setting. If the app forgets the WHERE clause, the database still hides
rows belonging to other tenants — that is the second layer of isolation.

`tenant_session(org_id)` is the recommended way to obtain a session in route
handlers. It sets the GUC, yields the session, and commits/rollbacks
appropriately.

For background jobs that span multiple tenants (cron, reports), use
`raw_session()` — the RLS policies see `current_setting('app.current_org_id', true)`
as NULL and a bypass policy applies only to rows where running as the database
owner. Be careful: such sessions must filter by org_id manually.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from salespilot.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Lazy-init the engine. Tests can call dispose_engine() between runs."""
    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            pool_recycle=300,
        )
        _sessionmaker = async_sessionmaker(
            _engine, expire_on_commit=False, autoflush=False
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None


@asynccontextmanager
async def tenant_session(org_id: UUID) -> AsyncIterator[AsyncSession]:
    """Yield an AsyncSession scoped to a single organization.

    Sets the `app.current_org_id` GUC for the lifetime of the session.
    All queries during this session see only rows where `org_id = :org_id`
    thanks to RLS policies installed by the initial migration.
    """
    sm = get_sessionmaker()
    async with sm() as session:
        # SET LOCAL does not accept bind params. We validate org_id as a UUID
        # before constructing the SQL, so this is safe from injection.
        assert isinstance(org_id, UUID), "org_id must be a UUID"
        await session.execute(
            text(f"SET LOCAL app.current_org_id = '{org_id}'")
        )
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def raw_session() -> AsyncIterator[AsyncSession]:
    """Yield a session without tenant scope.

    Use for: registration (no org yet), cross-tenant admin tasks, jobs.
    YOU are responsible for filtering by org_id where needed.
    """
    sm = get_sessionmaker()
    async with sm() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
