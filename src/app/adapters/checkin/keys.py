"""Services of the slice «відмітка присутності» by key (``app.services``), named ``checkin.*``.

The keys live here, not in ``app.slices.checkin``: the routes import them, and a route module
must import without the slice package (the foundation's tests swap ``app.slices`` for a sample).
"""

from app.adapters.checkin.texts import CheckinTexts
from app.core.checkin.ports import CheckinStore
from app.core.checkin.service import Attendance
from app.core.ports import RateLimiter
from app.services import Key

STORE = Key[CheckinStore]("checkin.store")
ATTENDANCE = Key[Attendance]("checkin.attendance")
RATE_LIMITER = Key[RateLimiter]("checkin.rate_limiter")
TEXTS = Key[CheckinTexts]("checkin.texts")
