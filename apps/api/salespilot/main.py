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
from salespilot.api.quotations import router as quotations_router
from salespilot.api.deals_enriched import router as deals_enriched_router
from salespilot.api.activities_enriched import router as activities_enriched_router
from salespilot.api.mail_campaigns import router as mail_campaigns_router
from salespilot.api.wespennest import router as wespennest_router
from salespilot.api.snelstart import router as snelstart_router
from salespilot.api.unifi import router as unifi_router
from salespilot.api.admin import router as admin_router
from salespilot.api.auth_m365 import router as auth_m365_router
from salespilot.api.oauth_callbacks import router as oauth_callbacks_router
from salespilot.api.sign import router as sign_router
from salespilot.api.calendar import router as calendar_router
from salespilot.api.social import router as social_router
from salespilot.api.companies_extra import router as companies_extra_comms_router
from salespilot.api.branding import router as branding_router, uploads_router as branding_uploads_router
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
    app.include_router(companies_extra_comms_router, prefix=prefix)
    app.include_router(companies_router, prefix=prefix)
    app.include_router(contacts_router, prefix=prefix)
    app.include_router(deals_router, prefix=prefix)
    app.include_router(activities_router, prefix=prefix)
    app.include_router(autopilot_router, prefix=prefix)
    app.include_router(quotations_router, prefix=prefix)
    app.include_router(deals_enriched_router, prefix=prefix)
    app.include_router(activities_enriched_router, prefix=prefix)
    app.include_router(mail_campaigns_router, prefix=prefix)
    app.include_router(wespennest_router, prefix=prefix)
    app.include_router(snelstart_router, prefix=prefix)
    app.include_router(unifi_router, prefix=prefix)
    app.include_router(admin_router, prefix=prefix)
    app.include_router(auth_m365_router, prefix=prefix)
    app.include_router(oauth_callbacks_router, prefix=prefix)
    # Sign portal is mounted WITHOUT the /api/v1 prefix because
    # sign.it-gemak.nl routes paths like /sign/ + /sign/api/* directly
    # to the API container.
    app.include_router(sign_router)
    app.include_router(calendar_router, prefix=prefix)
    app.include_router(social_router, prefix=prefix)
    app.include_router(branding_router, prefix=prefix)
    app.include_router(branding_uploads_router, prefix=prefix)
    app.include_router(autopilot_internal_router, prefix=prefix)
    app.include_router(autopilot_oauth_router, prefix=prefix)
    # Webhooks are intentionally mounted WITHOUT auth dependency; signature
    # verification happens inside each handler.
    app.include_router(autopilot_webhooks_router, prefix=prefix)

    return app


app = create_app()
