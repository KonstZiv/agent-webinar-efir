"""``LevelStore`` on the shared table ``participants``: one statement, only ``level``."""

from sqlalchemy import Engine, update

from app.adapters.db.models import Participant
from app.adapters.db.transaction import transaction


class SqlLevelStore:
    """``LevelStore`` backed by a SQLAlchemy engine."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def set_level(self, email: str, level: str) -> bool:
        statement = (
            update(Participant)
            .where(Participant.email == email)
            .values(level=level)
            .returning(Participant.id)
        )
        with transaction(self._engine, "set level") as session:
            return session.scalars(statement).first() is not None
