"""Services of the slice «лічильники й експорт» by key (``app.services``), named ``extras.*``.

The keys live here, not in ``app.slices.extras``: routes import them, and a route module must
import without the slice package (the foundation's tests swap ``app.slices`` for a sample).
"""

from app.core.extras.counters import CachedCounters
from app.core.extras.ports import ReportStore
from app.core.extras.statistics import Statistics
from app.services import Key

REPORTS = Key[ReportStore]("extras.reports")
COUNTERS = Key[CachedCounters]("extras.counters")
STATISTICS = Key[Statistics]("extras.statistics")
