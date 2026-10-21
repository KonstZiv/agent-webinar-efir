"""SQLAlchemy engine for PostgreSQL via psycopg 3."""

from sqlalchemy import Connection, Engine, create_engine, text

# Upper bound for every wait on the database: connecting, a free pool slot, unacknowledged
# network writes (also covers the pre-ping on a dead connection).
TIMEOUT_SECONDS = 2


def make_engine(database_url: str) -> Engine:
    """Create a lazily connecting engine; failures surface on first use, not at startup.

    ``database_url`` is already validated and normalised by ``Settings``. Error messages leave
    out statement parameters: they hold addresses and may reach a log.
    """
    return create_engine(
        database_url,
        hide_parameters=True,
        pool_pre_ping=True,
        pool_timeout=TIMEOUT_SECONDS,
        connect_args={
            "connect_timeout": TIMEOUT_SECONDS,
            "tcp_user_timeout": TIMEOUT_SECONDS * 1000,  # milliseconds; Linux only
        },
    )


def limit_statement_time(connection: Connection) -> None:
    """Bound every statement of the current transaction by ``TIMEOUT_SECONDS``.

    ``SET LOCAL`` ends with the transaction, so pooled connections stay unaffected.
    """
    connection.execute(text(f"SET LOCAL statement_timeout = {TIMEOUT_SECONDS * 1000}"))
