"""Database helpers for tests: engines that close their connections, a schema built by Alembic.

The fixtures built on them (``fresh_engine``, ``migrated_engine``, ``participant_factory``) live
in tests/conftest.py, so the tests of every slice see them.
"""

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text

from app.adapters.db.engine import make_engine

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def run_alembic(
    connection: Connection, action: Callable[[Config, str], None], revision: str
) -> None:
    config = Config(str(ALEMBIC_INI))
    config.attributes["connection"] = connection
    action(config, revision)


def migrate(engine: Engine, revision: str) -> None:
    """``alembic upgrade`` as on deploy: the migration environment owns the transaction."""
    with engine.connect() as connection:
        run_alembic(connection, command.upgrade, revision)


def downgrade(engine: Engine, revision: str) -> None:
    with engine.connect() as connection:
        run_alembic(connection, command.downgrade, revision)


def reset_schema(engine: Engine) -> None:
    """Drop everything a test left behind: rows of v2 kinds make ``downgrade`` impossible."""
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))


@contextmanager
def disposable_engine(url: str) -> Iterator[Engine]:
    """An engine built as the application builds it; its pool is closed when the block ends."""
    engine = make_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()


def wait_until_blocked(engine: Engine, seconds: float = 2) -> None:
    """Return once a session of the engine's database waits for a lock held by another one.

    Tests of concurrent writes hold a lock in one connection, start the operation in a thread
    and release the lock only after this: the order of events is fixed, not left to timing.
    """
    deadline = time.monotonic() + seconds
    with engine.connect() as observer:
        while time.monotonic() < deadline:
            waiting = observer.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity"
                    " WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            ).scalar_one()
            observer.rollback()  # statistics are read once per transaction
            if waiting:
                return
            time.sleep(0.02)
    raise AssertionError("no session waited for the lock")
