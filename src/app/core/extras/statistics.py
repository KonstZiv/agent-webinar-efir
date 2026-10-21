"""The operator's statistics, ``GET /admin/stats`` (docs/requirements.md, section 8).

``total`` and ``last_24h`` give v1's values on the same database (v1:
``webinar.core.statistics``): the day is counted by the application's clock. ``failed_emails``
keeps v1's key but counts the failed invitations only, those the retry of v2 sends; v2 never
sends v1's confirmation (section 8). A ``pending`` email older than 15 minutes is a failed one,
unless its ``scheduled_at`` is still ahead (section 6). The rule of «реєстрація і лист» is the
same, but slices do not import each other, hence the slice's own constant.
"""

from datetime import timedelta

from app.core.extras.ports import ReportStore, Stats
from app.core.ports import Clock

LAST_DAY = timedelta(hours=24)
STALE_PENDING_AFTER = timedelta(minutes=15)


class Statistics:
    """Reads the operator's numbers; storage errors reach the caller."""

    def __init__(self, *, store: ReportStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def current(self) -> Stats:
        return self._store.stats(self._clock.now() - LAST_DAY, STALE_PENDING_AFTER)
