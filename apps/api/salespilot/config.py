"""Application configuration, loaded from environment variables.

Settings are loaded once at import time and cached. To override during tests,
construct a Settings instance with explicit values and inject it.
"""

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    env: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    app_base_url: AnyHttpUrl = Field(default="http://localhost:8000")  # type: ignore[arg-type]

    # --- Database ---
    postgres_user: str = "salespilot"
    postgres_password: SecretStr = SecretStr("changeme_dev_only")
    postgres_db: str = "salespilot"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    @property
    def database_url(self) -> str:
        """SQLAlchemy async URL (asyncpg driver)."""
        pw = self.postgres_password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{pw}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        """Sync URL for Alembic (psycopg)."""
        pw = self.postgres_password.get_secret_value()
        return (
            f"postgresql+psycopg://{self.postgres_user}:{pw}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # --- Redis ---
    redis_password: SecretStr = SecretStr("changeme_dev_only")
    redis_host: str = "redis"
    redis_port: int = 6379

    @property
    def redis_url(self) -> str:
        pw = self.redis_password.get_secret_value()
        return f"redis://:{pw}@{self.redis_host}:{self.redis_port}/0"

    # --- Auth / tokens ---
    app_secret_key: SecretStr = SecretStr("please_replace")
    jwt_secret: SecretStr = SecretStr("please_replace")
    jwt_ttl_minutes: int = 60
    jwt_refresh_ttl_days: int = 30
    magic_link_ttl_minutes: int = 15

    # --- Mail ---
    smtp_host: str = ""  # empty = log magic links to stdout, don't send
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = "no-reply@example.com"
    smtp_starttls: bool = True

    # --- CORS ---
    # Stored as CSV string so pydantic-settings doesn't try to JSON-parse.
    # Use the `cors_origins` property to get a list[str].
    cors_origins_raw: str = Field(default="", alias="CORS_ORIGINS")

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
