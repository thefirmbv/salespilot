"""Schemas for the /integrations API."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class HaloPSAConfig(BaseModel):
    """Shape of the config_json for a HaloPSA integration."""

    base_url: str = Field(min_length=3, description="e.g. halo.it-gemak.nl")
    client_id: str = Field(min_length=1)
    client_secret: str = Field(min_length=1)
    tenant: str | None = None
    scopes: str = "all"


class IntegrationUpsert(BaseModel):
    is_enabled: bool = True
    config: HaloPSAConfig


class IntegrationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    is_enabled: bool
    # Never echo back client_secret. The route handler strips it.
    config_public: dict[str, Any]
    last_sync_at: datetime | None
    last_sync_status: str | None
    last_sync_message: str | None
    updated_at: datetime


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
