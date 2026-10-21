"""One time-bounded transaction per store operation; a database failure is a ``StorageError``.

Statements are bounded by ``TIMEOUT_SECONDS`` (``limit_statement_time``), so a request never
hangs on the database. Every SQLAlchemy failure becomes an exception of the port: an outage is
``StorageUnavailable``, a broken constraint ``StorageConflict``, anything else ``StorageError``.
The log names the operation and the error class only: driver messages may contain host and
database names and the data of the statement.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.orm import Session

from app.adapters.db.engine import limit_statement_time
from app.core.ports import StorageConflict, StorageError, StorageUnavailable

logger = logging.getLogger(__name__)

# Connection refused or lost, timeouts, lock waits.
_UNAVAILABLE = (OperationalError, InterfaceError, PoolTimeoutError)


@contextmanager
def transaction(engine: Engine, operation: str) -> Iterator[Session]:
    """A session in one transaction, committed when the block ends without an error."""
    try:
        with Session(engine, expire_on_commit=False) as session, session.begin():
            limit_statement_time(session.connection())
            yield session
    except SQLAlchemyError as error:
        logger.warning("Storage operation «%s» failed: %s", operation, type(error).__name__)
        if isinstance(error, _UNAVAILABLE):
            raise StorageUnavailable(operation) from None
        if isinstance(error, IntegrityError):
            raise StorageConflict(operation) from None
        raise StorageError(operation) from None
