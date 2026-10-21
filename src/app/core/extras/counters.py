"""The counters of the page, kept in memory up to 15 seconds (docs/requirements.md, section 8).

Hundreds of viewers poll every ``REFRESH_SECONDS``, and the service runs as one instance, so the
numbers live in memory: the database is read at most once per ``CACHE_TTL``. A failed read is
remembered for as long, so a database that is down does not hold every request in the thread
pool; the page then keeps what it shows. Nobody waits for another's read either: the polls
share the thread pool of every sync route of the site, ``/`` too.
"""

import threading
from datetime import datetime, timedelta

from app.core.extras.ports import Counts, CountSource
from app.core.ports import Clock, StorageError

CACHE_TTL = timedelta(seconds=15)
REFRESH_SECONDS = 15  # how often the page asks for the numbers


class CachedCounters:
    """The latest counts, read again once ``ttl`` has passed since the last read ended.

    Thread-safe. One call reads at a time; a call that comes while another reads answers at
    once with the latest numbers (``None`` before the first read ends), so the numbers may be
    older than ``ttl`` by the length of a read. A clock moved back makes the numbers old at once.
    """

    def __init__(self, source: CountSource, clock: Clock, ttl: timedelta = CACHE_TTL) -> None:
        self._source = source
        self._clock = clock
        self._ttl = ttl
        self._lock = threading.Lock()
        self._read_at: datetime | None = None
        self._counts: Counts | None = None

    def current(self) -> Counts | None:
        """The numbers, or ``None`` while the database fails (any ``StorageError``)."""
        if not self._lock.acquire(blocking=False):
            return self._counts  # another call reads: do not hold a thread of the site
        try:
            now = self._clock.now()
            if self._read_at is None or not timedelta(0) <= now - self._read_at < self._ttl:
                self._counts = self._read()
                self._read_at = self._clock.now()
            return self._counts
        finally:
            self._lock.release()

    def _read(self) -> Counts | None:
        try:
            return self._source.counts()
        except StorageError:  # the store has logged the operation and the error class
            return None
