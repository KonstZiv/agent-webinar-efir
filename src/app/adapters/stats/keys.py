"""Services of the slice «жива статистика» by key (``app.services``), named ``stats.*``.

The keys live here, not in ``app.slices.stats``: the route imports them, and a route module must
import without the slice package (the foundation's tests swap ``app.slices`` for a sample).
"""

from app.adapters.stats.texts import StatsTexts
from app.core.stats.cache import CachedStats
from app.core.stats.ports import GroupSource
from app.services import Key

GROUPS = Key[GroupSource]("stats.groups")
STATS = Key[CachedStats]("stats.cache")
TEXTS = Key[StatsTexts]("stats.texts")
