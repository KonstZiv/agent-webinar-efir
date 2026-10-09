"""Alembic environment: online migrations only.

Tests pass an open connection via ``config.attributes["connection"]``; then neither logging
nor settings are touched. Otherwise the URL comes from ``DATABASE_URL``.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection

from app.adapters.db.engine import make_engine
from app.adapters.db.models import Base
from app.settings import load_database_settings

config = context.config


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        run_migrations(connection)
        return

    if config.config_file_name is not None:
        fileConfig(config.config_file_name, disable_existing_loggers=False)
    engine = make_engine(load_database_settings().database_url.get_secret_value())
    try:
        with engine.connect() as connection:
            run_migrations(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline migrations are not supported; run against a database.")
run_migrations_online()
