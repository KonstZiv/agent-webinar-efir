"""The slice «жива статистика»: the public page ``/stats`` with aggregates only.

``install`` provides the slice's services by key (``app.adapters.stats.keys``). The texts
(docs/copy.md, 12.2) and the level names (docs/quiz.md) are read at startup, like the texts of
the foundation; the numbers are read from the shared tables through the application's engine,
once per 30 seconds, on the first visit.
"""

from pathlib import Path

from app.adapters.stats.groups import SqlGroupSource
from app.adapters.stats.keys import GROUPS, STATS, TEXTS
from app.adapters.stats.texts import load_level_names, load_texts
from app.core.stats.cache import CachedStats
from app.services import CLOCK
from app.slices import SliceSetup

# Texts live in the repository's docs/; the working directory is the repository (as in main.py).
DOCS_DIR = Path("docs")


def install(setup: SliceSetup) -> None:
    services = setup.services
    texts = load_texts(DOCS_DIR)
    level_names = load_level_names(DOCS_DIR)
    setup.provide(GROUPS, lambda: SqlGroupSource(setup.engine()))
    setup.provide(
        STATS, lambda: CachedStats(services.get(GROUPS), services.get(CLOCK), level_names)
    )
    setup.provide(TEXTS, lambda: texts)
