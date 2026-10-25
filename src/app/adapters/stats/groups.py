"""``GroupSource`` on the shared table ``participants`` (v1 writes it too).

Read-only, one statement in one time-bounded transaction (``transaction``): one snapshot, so the
groups agree while people register, and a failure becomes a ``StorageError``. The statement
returns counts only; no address or identifier is selected.
"""

from datetime import datetime

from sqlalchemy import Engine, case, func, select

from app.adapters.db.models import Participant
from app.adapters.db.transaction import transaction
from app.core.stats.ports import Group


class SqlGroupSource:
    """``GroupSource`` backed by a SQLAlchemy engine."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def groups(self, since: datetime) -> list[Group]:
        linked = Participant.tg_user_id.is_not(None)
        # The hour is cut in UTC whatever the session's zone is: Kyiv's hours begin at the same
        # moments, as its offsets are whole hours.
        hour = case(
            (
                Participant.registered_at >= since,
                func.date_trunc("hour", Participant.registered_at, "UTC"),
            ),
            else_=None,
        )
        statement = select(Participant.level, linked, hour, func.count()).group_by(
            Participant.level, linked, hour
        )
        with transaction(self._engine, "group participants") as session:
            return [
                Group(level=level, telegram_linked=is_linked, hour=at, count=count)
                for level, is_linked, at, count in session.execute(statement)
            ]
