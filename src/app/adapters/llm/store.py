"""The classification in ``participants.extra["llm"]``: the slice's own SQL.

The shared ``ParticipantStore`` stays as it is. One statement merges the key ``llm`` into
``extra`` and leaves the other keys; it touches the participant linked to this Telegram, and
no row at all for a person who is not linked.
"""

import json

from sqlalchemy import Engine, text

from app.adapters.db.transaction import transaction
from app.core.llm.classification import Classification

_SAVE = text(
    """
    UPDATE participants
       SET extra = coalesce(extra, '{}'::jsonb)
                   || jsonb_build_object('llm', CAST(:value AS jsonb))
     WHERE tg_user_id = :tg_user_id
    """
)


class SqlClassificationStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def save(self, telegram_user_id: int, classification: Classification) -> bool:
        value = json.dumps(classification.as_json())
        with transaction(self._engine, "save classification") as session:
            result = session.execute(_SAVE, {"value": value, "tg_user_id": telegram_user_id})
            return result.rowcount > 0  # type: ignore[attr-defined]
