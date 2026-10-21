"""``LinkTokenStore`` on the table ``link_tokens``: data operations only.

Whether a token is still valid or may move a Telegram link is decided by the slices; the store
keeps the first use time and the latest user. Single use is a condition of the claiming
statement, so concurrent requests cannot both take a token.
"""

from datetime import datetime
from typing import cast

from sqlalchemy import Engine, func, or_, select, update

from app.adapters.db.models import LinkToken as LinkTokenRow
from app.adapters.db.transaction import transaction
from app.core.entities import LinkSource, LinkToken


def _link_token(row: LinkTokenRow) -> LinkToken:
    return LinkToken(
        token=row.token,
        participant_id=row.participant_id,
        source=cast(LinkSource, row.source),  # the database check allows these two only
        created_at=row.created_at,
        expires_at=row.expires_at,
        used_at=row.used_at,
        used_by_tg_user_id=row.used_by_tg_user_id,
    )


class SqlLinkTokenStore:
    """``LinkTokenStore`` backed by a SQLAlchemy engine."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, token: LinkToken) -> None:
        with transaction(self._engine, "add link token") as session:
            session.add(
                LinkTokenRow(
                    participant_id=token.participant_id,
                    token=token.token,
                    source=token.source,
                    created_at=token.created_at,
                    expires_at=token.expires_at,
                    used_at=token.used_at,
                    used_by_tg_user_id=token.used_by_tg_user_id,
                )
            )

    def find(self, token: str) -> LinkToken | None:
        with transaction(self._engine, "find link token") as session:
            row = session.scalars(
                select(LinkTokenRow).where(LinkTokenRow.token == token)
            ).one_or_none()
            return _link_token(row) if row is not None else None

    def claim(self, token: str, tg_user_id: int, at: datetime) -> bool:
        statement = (
            update(LinkTokenRow)
            .where(
                LinkTokenRow.token == token,
                or_(LinkTokenRow.used_at.is_(None), LinkTokenRow.used_by_tg_user_id == tg_user_id),
            )
            .values(used_at=func.coalesce(LinkTokenRow.used_at, at), used_by_tg_user_id=tg_user_id)
            .returning(LinkTokenRow.id)
            .execution_options(synchronize_session=False)
        )
        with transaction(self._engine, "claim link token") as session:
            return session.execute(statement).scalar_one_or_none() is not None

    def record_use(self, token: str, tg_user_id: int, at: datetime) -> bool:
        statement = (
            update(LinkTokenRow)
            .where(LinkTokenRow.token == token)
            .values(used_at=func.coalesce(LinkTokenRow.used_at, at), used_by_tg_user_id=tg_user_id)
            .returning(LinkTokenRow.id)
            .execution_options(synchronize_session=False)
        )
        with transaction(self._engine, "record link token use") as session:
            return session.execute(statement).scalar_one_or_none() is not None
