"""``ParticipantStore`` on the shared table ``participants`` (v1 writes it too).

Data operations only: one row per address, one participant per Telegram account. Conditions
that concurrent requests could break live in the statements themselves. Row locks are
``FOR NO KEY UPDATE`` at most: v1 holds ``FOR KEY SHARE`` on a participant while it sends their
email, and that must not wait for v2. The rules of registration and of the bot live in their
slices.
"""

import uuid
from datetime import datetime

from sqlalchemy import ColumnElement, Engine, case, delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased

from app.adapters.db.models import Participant as ParticipantRow
from app.adapters.db.transaction import transaction
from app.core.entities import NewParticipant, Participant, TelegramAccount


def _participant(row: ParticipantRow) -> Participant:
    telegram = (
        TelegramAccount(row.tg_user_id, row.tg_username) if row.tg_user_id is not None else None
    )
    return Participant(
        id=row.id,
        email=row.email,
        unsubscribe_id=row.unsubscribe_id,
        registered_at=row.registered_at,
        origin=row.origin,
        telegram=telegram,
        telegram_linked_at=row.tg_linked_at,
        channel_member=row.channel_member,
        level=row.level,
        ref_code=row.ref_code,
        referred_by=row.referred_by,
    )


class SqlParticipantStore:
    """``ParticipantStore`` backed by a SQLAlchemy engine."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add_if_absent(self, participant: NewParticipant) -> tuple[Participant, bool]:
        source = participant.source
        statement = (
            insert(ParticipantRow)
            .values(
                email=participant.email,
                unsubscribe_id=participant.unsubscribe_id,
                registered_at=participant.registered_at,
                consent_version=participant.consent_version,
                consent_at=participant.consent_at,
                utm_source=source.utm_source,
                utm_medium=source.utm_medium,
                utm_campaign=source.utm_campaign,
                utm_term=source.utm_term,
                utm_content=source.utm_content,
                gclid=source.gclid,
                gbraid=source.gbraid,
                wbraid=source.wbraid,
                landing_url=source.landing_url,
                referrer=source.referrer,
                ga_client_id=participant.ga_client_id,
                origin=participant.origin,
            )
            # The existing row comes back unchanged and locked until the end of the statement's
            # transaction. A column outside unique indexes keeps the lock FOR NO KEY UPDATE.
            .on_conflict_do_update(
                index_elements=[ParticipantRow.email],
                set_={ParticipantRow.registered_at: ParticipantRow.registered_at},
            )
            .returning(ParticipantRow)
        )
        with transaction(self._engine, "add participant") as session:
            row = session.scalars(statement).one()
            # Only a row this statement inserted carries this call's new unsubscribe id.
            return _participant(row), row.unsubscribe_id == participant.unsubscribe_id

    def by_id(self, participant_id: int) -> Participant | None:
        return self._find("find participant", ParticipantRow.id == participant_id)

    def by_email(self, email: str) -> Participant | None:
        return self._find("find participant", ParticipantRow.email == email)

    def by_unsubscribe_id(self, unsubscribe_id: uuid.UUID) -> Participant | None:
        return self._find("find participant", ParticipantRow.unsubscribe_id == unsubscribe_id)

    def by_telegram(self, tg_user_id: int) -> Participant | None:
        return self._find("find participant", ParticipantRow.tg_user_id == tg_user_id)

    def remove_by_unsubscribe_id(self, unsubscribe_id: uuid.UUID) -> bool:
        statement = (
            delete(ParticipantRow)
            .where(ParticipantRow.unsubscribe_id == unsubscribe_id)
            .returning(ParticipantRow.id)
        )
        with transaction(self._engine, "remove participant") as session:
            return session.execute(statement).scalar_one_or_none() is not None

    def link_telegram_if_free(
        self, participant_id: int, account: TelegramAccount, at: datetime
    ) -> bool:
        other = aliased(ParticipantRow)
        account_taken = select(other.id).where(other.tg_user_id == account.user_id).exists()
        statement = (
            update(ParticipantRow)
            .where(
                ParticipantRow.id == participant_id,
                ParticipantRow.tg_user_id.is_(None),
                ~account_taken,
            )
            .values(
                tg_user_id=account.user_id,
                tg_username=account.username,
                tg_linked_at=at,
                channel_member=None,
            )
            .returning(ParticipantRow.id)
            .execution_options(synchronize_session=False)
        )
        with transaction(self._engine, "link free telegram") as session:
            return session.execute(statement).scalar_one_or_none() is not None

    def transfer_telegram(
        self, participant_id: int, account: TelegramAccount, at: datetime
    ) -> bool:
        same_account = ParticipantRow.tg_user_id == account.user_id
        with transaction(self._engine, "transfer telegram") as session:
            found = session.execute(
                select(ParticipantRow.id)
                .where(ParticipantRow.id == participant_id)
                .with_for_update(key_share=True)  # FOR NO KEY UPDATE
            ).scalar_one_or_none()
            if found is None:
                return False
            session.execute(
                update(ParticipantRow)
                .where(same_account, ParticipantRow.id != participant_id)
                .values(tg_user_id=None, tg_username=None, tg_linked_at=None, channel_member=None)
                .execution_options(synchronize_session=False)
            )
            # SET expressions see the old row: the same account keeps its link time and check.
            session.execute(
                update(ParticipantRow)
                .where(ParticipantRow.id == participant_id)
                .values(
                    tg_user_id=account.user_id,
                    tg_username=account.username,
                    tg_linked_at=case((same_account, ParticipantRow.tg_linked_at), else_=at),
                    channel_member=case((same_account, ParticipantRow.channel_member), else_=None),
                )
                .execution_options(synchronize_session=False)
            )
            return True

    def set_channel_member(self, participant_id: int, tg_user_id: int, member: bool) -> bool:
        statement = (
            update(ParticipantRow)
            .where(ParticipantRow.id == participant_id, ParticipantRow.tg_user_id == tg_user_id)
            .values(channel_member=member)
            .returning(ParticipantRow.id)
            .execution_options(synchronize_session=False)
        )
        with transaction(self._engine, "set channel member") as session:
            return session.execute(statement).scalar_one_or_none() is not None

    def _find(self, operation: str, condition: ColumnElement[bool]) -> Participant | None:
        with transaction(self._engine, operation) as session:
            row = session.scalars(select(ParticipantRow).where(condition)).one_or_none()
            return _participant(row) if row is not None else None
