"""Database fixtures: engines that close their connections, a schema built by Alembic."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine

from app.adapters.db.engine import make_engine

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def run_alembic(
    connection: Connection, action: Callable[[Config, str], None], revision: str
) -> None:
    config = Config(str(ALEMBIC_INI))
    config.attributes["connection"] = connection
    action(config, revision)


@contextmanager
def disposable_engine(url: str) -> Iterator[Engine]:
    """An engine built as the application builds it; its pool is closed when the block ends."""
    engine = make_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def migrated_engine(test_db_url: str) -> Iterator[Engine]:
    with disposable_engine(test_db_url) as engine:
        with engine.begin() as connection:
            run_alembic(connection, command.upgrade, "head")
        try:
            yield engine
        finally:
            with engine.begin() as connection:
                run_alembic(connection, command.downgrade, "base")
