"""Alembic environment.

Uses the sync DB URL (psycopg) and pulls metadata from our SQLAlchemy models
so `alembic revision --autogenerate` picks up new tables/columns.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from salespilot.config import get_settings

# Import models so their tables register on Base.metadata.
from salespilot.models import Base  # noqa: F401
from salespilot.models import auth as _auth  # noqa: F401
from salespilot.models import crm as _crm  # noqa: F401
from salespilot.models import integrations as _int  # noqa: F401
from salespilot.models import visitor as _vis  # noqa: F401
from salespilot.models import autopilot as _auto  # noqa: F401
from salespilot.models import quotation as _quot  # noqa: F401
from salespilot.models import mail_campaign as _mc  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url_sync)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
