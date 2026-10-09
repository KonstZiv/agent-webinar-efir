"""Database availability check for ``/healthz``."""

import logging

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.db.engine import limit_statement_time

logger = logging.getLogger(__name__)


class SqlDatabaseProbe:
    """``DatabaseProbe`` backed by a SQLAlchemy engine; every step is time-bounded."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def is_available(self) -> bool:
        try:
            with self._engine.connect() as connection:
                limit_statement_time(connection)
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError as error:
            # Only the class name: driver messages may contain host and database names.
            logger.warning("Database health check failed: %s", type(error).__name__)
            return False
        return True
