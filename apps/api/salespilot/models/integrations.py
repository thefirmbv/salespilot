"""External system integrations per organization."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from salespilot.models import Base, TenantScoped, Timestamps, UUIDPrimaryKey


class Integration(UUIDPrimaryKey, TenantScoped, Timestamps, Base):
    """Per-org credentials and state for an external system (HaloPSA, etc.).

    One row per (org_id, kind). `kind` is a free string like 'halopsa'.
    `config_json` holds the kind-specific configuration. For HaloPSA:

        {
          "base_url": "halo.it-gemak.nl",
          "client_id": "...",
          "client_secret": "...",
          "tenant": null,
          "scopes": "all"
        }

    Secrets are stored as plain JSON for v1; encryption-at-rest in the app
    layer is on the TODO list (see ARCHITECTURE.md).
    """

    __tablename__ = "integrations"
    __table_args__ = (
        UniqueConstraint("org_id", "kind", name="uq_integrations_org_kind"),
    )

    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    config_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str | None] = mapped_column(String(20))
    last_sync_message: Mapped[str | None] = mapped_column(Text)
