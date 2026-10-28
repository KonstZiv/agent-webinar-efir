"""The slice «відмітка присутності»: marks on the lessons, groups, the teacher's admin API.

``install`` provides the slice's services by key (``app.adapters.checkin.keys``), among them the
scenarios for the bot of Telegram under ``checkin.telegram`` (the bot finds them, never imports
this slice), and gives
``_checkin.html`` its values (template global ``checkin``). The texts (docs/copy.md, section 14)
are read at startup; the data goes through the application's engine. Attempts at ``/checkin``
are limited to ``ATTEMPTS`` per ``WINDOW`` from one address.
"""

from datetime import timedelta
from pathlib import Path

from app.adapters.checkin.keys import (
    ADMIN_TEXTS,
    ATTENDANCE,
    RATE_LIMITER,
    STORE,
    TELEGRAM,
    TEXTS,
)
from app.adapters.checkin.store import SqlCheckinStore
from app.adapters.checkin.telegram import TelegramAttendance
from app.adapters.checkin.texts import load_admin_texts, load_texts
from app.adapters.checkin.view import CheckinPartial
from app.adapters.ratelimit.memory import InMemoryRateLimiter
from app.core.checkin.service import Attendance
from app.services import CLOCK, PARTICIPANTS
from app.slices import SliceSetup

# Texts live in the repository's docs/; the working directory is the repository (as in main.py).
DOCS_DIR = Path("docs")
ATTEMPTS = 10
WINDOW = timedelta(minutes=1)


def install(setup: SliceSetup) -> None:
    services = setup.services
    texts = load_texts(DOCS_DIR)
    admin_texts = load_admin_texts(DOCS_DIR)

    def attendance() -> Attendance:
        return Attendance(
            services.get(STORE),
            services.get(PARTICIPANTS),
            services.get(CLOCK),
            services.get(RATE_LIMITER),
        )

    setup.provide(STORE, lambda: SqlCheckinStore(setup.engine()))
    setup.provide(
        RATE_LIMITER,
        lambda: InMemoryRateLimiter(limit=ATTEMPTS, window=WINDOW, clock=services.get(CLOCK)),
    )
    setup.provide(ATTENDANCE, attendance)
    setup.provide(TELEGRAM, lambda: TelegramAttendance(services.get(ATTENDANCE)))
    setup.provide(TEXTS, lambda: texts)
    setup.provide(ADMIN_TEXTS, lambda: admin_texts)
    setup.template_global("checkin", CheckinPartial(texts))
