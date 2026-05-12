"""FastAPI app entrypoint.

Mounts:
  /healthz                 — liveness probe (no auth)
  /api/v1/auth/*           — registration, login, magic-link, refresh, me
  /api/v1/companies        — CRUD
  /api/v1/contacts         — CRUD
  /api/v1/deals            — CRUD
  /api/v1/activities       — CRUD
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from salespilot.api.auth import router as auth_router
from salespilot.api.dashboard import router as dashboard_router
from salespilot.api.autopilot import router as autopilot_router
from salespilot.api.jobs_and_webhooks import (
    internal_router as autopilot_internal_router,
    webhooks_router as autopilot_webhooks_router,
    oauth_router as autopilot_oauth_router,
)
from salespilot.api.integrations import router as integrations_router, companies_extra_router as halopsa_company_router
from salespilot.api.pipelines import router as pipelines_router
from salespilot.api.crm import (
    activities_router,
    companies_router,
    contacts_router,
    deals_router,
)
from salespilot.config import get_settings
from salespilot.db import dispose_engine

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    log.info("Starting SalesPilot API env=%s", settings.env)
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="SalesPilot API",
        version="0.1.0",
        lifespan=lifespan,
        # Disable docs in production unless we explicitly want them.
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
        openapi_url="/openapi.json" if not settings.is_production else None,
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/healthz", tags=["meta"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    prefix = "/api/v1"
    app.include_router(auth_router, prefix=prefix)
    app.include_router(pipelines_router, prefix=prefix)
    app.include_router(dashboard_router, prefix=prefix)
    app.include_router(integrations_router, prefix=prefix)
    app.include_router(halopsa_company_router, prefix=prefix)
    app.include_router(companies_router, prefix=prefix)
    app.include_router(contacts_router, prefix=prefix)
    app.include_router(deals_router, prefix=prefix)
    app.include_router(activities_router, prefix=prefix)
    app.include_router(autopilot_router, prefix=prefix)
    app.include_router(autopilot_internal_router, prefix=prefix)
    app.include_router(autopilot_oauth_router, prefix=prefix)
    # Webhooks are intentionally mounted WITHOUT auth dependency; signature
    # verification happens inside each handler.
    app.include_router(autopilot_webhooks_router, prefix=prefix)

    return app


app = create_app()
