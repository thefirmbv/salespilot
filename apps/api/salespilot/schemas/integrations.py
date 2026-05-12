"""Schemas for the /integrations API.

Each integration uses its own config_json shape. The IntegrationPublic
response masks secrets; the config_public dict only includes safe-to-display
keys (e.g. base_url, client_id) plus boolean *_set markers for secrets.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---- HaloPSA ----


class HaloPSAConfig(BaseModel):
    base_url: str = Field(min_length=3, description="e.g. halo.it-gemak.nl")
    client_id: str = Field(min_length=1)
    client_secret: str = Field(min_length=1)
    tenant: str | None = None
    scopes: str = "all"


# ---- ProspectPRO ----


class ProspectPROConfig(BaseModel):
    """ProspectPRO API uses a single API key for auth.

    Base URL defaults to mijn.prospectpro.nl. Docs:
    https://docs.prospectpro.nl/
    """

    base_url: str = Field(default="api.prospectpro.nl")
    api_key: str = Field(min_length=1)


# ---- Anthropic ----


class AnthropicConfig(BaseModel):
    api_key: str = Field(min_length=8)
    model: str = "claude-sonnet-4-5-20250929"


# ---- Generic upsert / public ----


class IntegrationUpsert(BaseModel):
    is_enabled: bool = True
    config: dict[str, Any]


class IntegrationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    is_enabled: bool
    config_public: dict[str, Any]
    last_sync_at: datetime | None
    last_sync_status: str | None
    last_sync_message: str | None
    updated_at: datetime


class IntegrationSummary(BaseModel):
    """Listed in the connector grid: one entry per known kind, whether
    configured or not."""

    kind: str
    label: str
    description: str
    is_configured: bool
    is_enabled: bool
    last_sync_at: datetime | None = None
    last_sync_status: str | None = None
    extra: dict[str, Any] = {}


class TestConnectionResult(BaseModel):
    ok: bool
    detail: str
    token_present: bool = False


class SyncResult(BaseModel):
    ok: bool
    detail: str
    fetched: int = 0
    created: int = 0
    updated: int = 0


# ---- Callscript ----


class CallscriptStep(BaseModel):
    title: str
    content: str


class Callscript(BaseModel):
    company_id: UUID
    generated_at: datetime
    model: str
    steps: list[CallscriptStep]
    context_summary: str
    website_summary: str | None = None
    decision_maker_hint: str | None = None
