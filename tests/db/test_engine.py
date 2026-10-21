"""Every wait on the database is bounded, so /healthz cannot hang a worker."""

import time
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.exc import DBAPIError

from app.adapters.db.engine import TIMEOUT_SECONDS
from app.adapters.db.probe import SqlDatabaseProbe
from tests.database import disposable_engine


@pytest.fixture
def engine(test_db_url: str) -> Iterator[Engine]:
    with disposable_engine(test_db_url) as engine:
        yield engine


def test_disposable_engine_closes_pooled_connections(test_db_url: str) -> None:
    """Tests leave no sessions open on the test database."""
    with disposable_engine(test_db_url) as engine:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        assert engine.pool.checkedin() == 1

    assert engine.pool.checkedin() == 0


def test_pool_checkout_wait_is_bounded(engine: Engine) -> None:
    assert engine.pool.timeout() == TIMEOUT_SECONDS


def test_connection_uses_connect_and_tcp_timeouts(engine: Engine) -> None:
    with engine.connect() as connection:
        params = connection.connection.dbapi_connection.info.get_parameters()  # type: ignore[union-attr]

    assert params["connect_timeout"] == str(TIMEOUT_SECONDS)
    assert params["tcp_user_timeout"] == str(TIMEOUT_SECONDS * 1000)


def test_probe_limits_its_statement_time(engine: Engine) -> None:
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append(args[2]))

    assert SqlDatabaseProbe(engine).is_available() is True
    assert any("statement_timeout" in statement for statement in statements)
    assert statements.index(next(s for s in statements if "statement_timeout" in s)) < next(
        index for index, statement in enumerate(statements) if statement.strip() == "SELECT 1"
    )


def test_probe_statement_timeout_does_not_leak_into_pool(engine: Engine) -> None:
    SqlDatabaseProbe(engine).is_available()

    with engine.connect() as connection:
        assert connection.execute(text("SHOW statement_timeout")).scalar_one() == "0"


def test_probe_gives_up_when_pool_is_exhausted(engine: Engine) -> None:
    held = [engine.connect() for _ in range(engine.pool.size() + engine.pool._max_overflow)]  # type: ignore[attr-defined]
    try:
        started = time.monotonic()
        available = SqlDatabaseProbe(engine).is_available()
        elapsed = time.monotonic() - started
    finally:
        for connection in held:
            connection.close()

    assert available is False
    assert elapsed < TIMEOUT_SECONDS + 1


def test_errors_never_carry_statement_parameters(engine: Engine) -> None:
    """A failed statement's message may reach a log: the values it was given stay out of it."""
    with engine.connect() as connection, pytest.raises(DBAPIError) as failure:
        connection.execute(text("SELECT :email AS email, 1 / 0"), {"email": "visitor@example.com"})

    assert "visitor@example.com" not in str(failure.value)
