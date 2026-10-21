"""The numbers of ``/stats``, kept in memory for 30 seconds (the issue «Statistic»).

As the counters of «лічильники й експорт» (``CachedCounters``), but for 30 seconds: the database
is read at most once per ``CACHE_TTL`` however many visit, and a failed read is remembered for as
long, so a database that is down does not hold every request in the thread pool of the site.
Unlike the counters, a failed read keeps the last known numbers: the page shows them, and the
message only when there are none yet.
"""

import threading
from collections.abc import Mapping
from datetime import datetime, timedelta

from app.core.ports import Clock, StorageError
from app.core.stats.ports import GroupSource
from app.core.stats.view import StatsView, build_view, window_start

CACHE_TTL = timedelta(seconds=30)


class CachedStats:
    """The latest view, read again once ``ttl`` has passed since the last read ended.

    Thread-safe. One call reads at a time; a call that comes while another reads answers at
    once with the latest view (``None`` before the first good read), so the numbers may be
    older than ``ttl`` by the length of a read. A clock moved back makes the view old at once.
    """

    def __init__(
        self,
        source: GroupSource,
        clock: Clock,
        level_names: Mapping[str, str],
        ttl: timedelta = CACHE_TTL,
    ) -> None:
        self._source = source
        self._clock = clock
        self._level_names = level_names
        self._ttl = ttl
        self._lock = threading.Lock()
        self._read_at: datetime | None = None
        self._view: StatsView | None = None

    def current(self) -> StatsView | None:
        """The numbers; the last known ones while the database fails, ``None`` before any."""
        if not self._lock.acquire(blocking=False):
            return self._view  # another call reads: do not hold a thread of the site
        try:
            now = self._clock.now()
            if self._read_at is None or not timedelta(0) <= now - self._read_at < self._ttl:
                self._read(now)
                self._read_at = self._clock.now()
            return self._view
        finally:
            self._lock.release()

    def _read(self, now: datetime) -> None:
        try:
            groups = self._source.groups(window_start(now))
        except StorageError:  # the store has logged the operation and the error class
            return
        self._view = build_view(groups, now, self._level_names)
