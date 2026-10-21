"""``InvitationStore`` on the shared table ``emails`` (v1 writes its ``confirmation`` there too).

One ``lesson_invitation`` per participant: the unique ``(participant_id, kind)`` keeps a second
row out even under a race. Registration claims the row before it answers; the background starts
sending only if the row is still that claim (``updated_at`` unchanged), so an invitation that
waited too long and was taken by the operator's retry is not sent twice, and an outcome is
recorded only by the claim that sent it (a ``sent`` email is never overwritten). The participant is
read ``FOR KEY SHARE``, as v1 does for its email:
an unsubscribe in flight finishes first, and nobody deletes the participant under the insert.
The operator's retry locks ``FOR NO KEY UPDATE … SKIP LOCKED``, no more (the foundation's rule:
v1 holds ``FOR KEY SHARE`` on a participant while it sends). There is no trigger in the
database: every change stamps ``updated_at`` itself, as v1 does.
"""

import dataclasses
import uuid
from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import ColumnElement, Engine, and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from app.adapters.db.models import EmailRecord, Participant
from app.adapters.db.models import LinkToken as LinkTokenRow
from app.adapters.db.transaction import transaction
from app.core.entities import Delivered, DeliveryResult, LinkSource, LinkToken
from app.core.registration.ports import ClaimedEmail

KIND = "lesson_invitation"
LAST_ERROR_LENGTH = 500
EMAIL_SOURCE = "email"


def _awaiting_resend(stale_after: timedelta) -> ColumnElement[bool]:
    """A failed email, or a «pending» one whose process died, unless scheduled for later.

    ``updated_at`` is the database clock, so the age is measured by it too (requirements, 6).
    """
    stale = EmailRecord.updated_at < func.now() - stale_after
    due = or_(EmailRecord.scheduled_at.is_(None), EmailRecord.scheduled_at <= func.now())
    return and_(
        or_(EmailRecord.status == "failed", and_(EmailRecord.status == "pending", stale)), due
    )


class SqlInvitationStore:
    """``InvitationStore`` backed by a SQLAlchemy engine."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def claim(
        self, participant_id: int, idempotency_key: uuid.UUID, stale_after: timedelta
    ) -> ClaimedEmail | None:
        with transaction(self._engine, "claim invitation") as session:
            participant = session.execute(
                select(Participant.email, Participant.unsubscribe_id)
                .where(Participant.id == participant_id)
                .with_for_update(read=True, key_share=True)  # FOR KEY SHARE
            ).first()
            if participant is None:
                return None
            # A new row, or nothing when the participant already has one (also under a race).
            row = session.execute(
                insert(EmailRecord)
                .values(
                    participant_id=participant_id,
                    kind=KIND,
                    status="pending",
                    idempotency_key=idempotency_key,
                    attempts=0,
                )
                .on_conflict_do_nothing(
                    index_elements=[EmailRecord.participant_id, EmailRecord.kind]
                )
                .returning(EmailRecord.id, EmailRecord.idempotency_key, EmailRecord.updated_at)
            ).first()
            if row is None:
                # Taken again: a failed email, or a «pending» one whose process died. The row
                # lock makes concurrent claims wait; they then see a fresh «pending».
                row = session.execute(
                    update(EmailRecord)
                    .where(
                        EmailRecord.participant_id == participant_id,
                        EmailRecord.kind == KIND,
                        _awaiting_resend(stale_after),
                    )
                    .values(status="pending", updated_at=func.now())
                    .returning(EmailRecord.id, EmailRecord.idempotency_key, EmailRecord.updated_at)
                    .execution_options(synchronize_session=False)
                ).first()
            if row is None:
                return None
            return ClaimedEmail(
                id=row.id,
                participant_id=participant_id,
                recipient=participant.email,
                unsubscribe_id=participant.unsubscribe_id,
                idempotency_key=row.idempotency_key,
                claimed_at=row.updated_at,
            )

    def start(self, claimed: ClaimedEmail) -> ClaimedEmail | None:
        statement = (
            update(EmailRecord)
            .where(
                EmailRecord.id == claimed.id,
                EmailRecord.status == "pending",
                EmailRecord.updated_at == claimed.claimed_at,
            )
            .values(updated_at=func.now())
            .returning(EmailRecord.updated_at)
            .execution_options(synchronize_session=False)
        )
        with transaction(self._engine, "start invitation") as session:
            started = session.execute(statement).scalar_one_or_none()
        if started is None:
            return None
        return dataclasses.replace(claimed, claimed_at=started)

    def database_now(self) -> datetime:
        with transaction(self._engine, "read the database clock") as session:
            return session.execute(select(func.now())).scalar_one()

    def claim_failed(self, stale_after: timedelta, changed_before: datetime) -> ClaimedEmail | None:
        with transaction(self._engine, "claim failed invitation") as session:
            # SKIP LOCKED: a row a parallel retry holds, or a participant an unsubscribe is
            # deleting, is passed by. Claiming and recording both stamp ``updated_at``, so a row
            # changed since the call began is left alone; the least recently changed goes first.
            row = session.execute(
                select(
                    EmailRecord.id,
                    EmailRecord.participant_id,
                    EmailRecord.idempotency_key,
                    Participant.email,
                    Participant.unsubscribe_id,
                )
                .join(Participant, Participant.id == EmailRecord.participant_id)
                .where(
                    EmailRecord.kind == KIND,
                    _awaiting_resend(stale_after),
                    EmailRecord.updated_at < changed_before,
                )
                .order_by(EmailRecord.updated_at, EmailRecord.id)
                .limit(1)
                .with_for_update(
                    of=[EmailRecord.__table__, Participant.__table__],
                    key_share=True,  # FOR NO KEY UPDATE
                    skip_locked=True,
                )
            ).first()
            if row is None:
                return None
            claimed_at = session.execute(
                update(EmailRecord)
                .where(EmailRecord.id == row.id)
                .values(status="pending", updated_at=func.now())
                .returning(EmailRecord.updated_at)
                .execution_options(synchronize_session=False)
            ).scalar_one()
            return ClaimedEmail(
                id=row.id,
                participant_id=row.participant_id,
                recipient=row.email,
                unsubscribe_id=row.unsubscribe_id,
                idempotency_key=row.idempotency_key,
                claimed_at=claimed_at,
            )

    def record_delivery(
        self,
        claimed: ClaimedEmail,
        result: DeliveryResult,
        at: datetime,
        next_key: uuid.UUID | None,
    ) -> bool:
        if isinstance(result, Delivered):
            values: dict[str, object] = {
                "status": "sent",
                "sent_at": at,
                "resend_id": result.provider_id or None,
                "last_error": None,
            }
        else:
            values = {"status": "failed", "last_error": result.error[:LAST_ERROR_LENGTH]}
            if next_key is not None:
                values["idempotency_key"] = next_key
        statement = (
            update(EmailRecord)
            .where(
                EmailRecord.id == claimed.id,
                EmailRecord.status == "pending",
                EmailRecord.updated_at == claimed.claimed_at,
            )
            .values(
                **values, attempts=EmailRecord.attempts + result.attempts, updated_at=func.now()
            )
            .returning(EmailRecord.id)
            .execution_options(synchronize_session=False)
        )
        with transaction(self._engine, "record invitation") as session:
            return session.execute(statement).first() is not None

    def latest_email_token(self, participant_id: int, issued_since: datetime) -> LinkToken | None:
        statement = (
            select(LinkTokenRow)
            .where(
                LinkTokenRow.participant_id == participant_id,
                LinkTokenRow.source == EMAIL_SOURCE,
                LinkTokenRow.created_at >= issued_since,
            )
            .order_by(LinkTokenRow.created_at.desc(), LinkTokenRow.id.desc())
            .limit(1)
        )
        with transaction(self._engine, "find email link token") as session:
            row = session.scalars(statement).first()
            if row is None:
                return None
            return LinkToken(
                token=row.token,
                participant_id=row.participant_id,
                source=cast(LinkSource, row.source),  # the database check allows two values
                created_at=row.created_at,
                expires_at=row.expires_at,
                used_at=row.used_at,
                used_by_tg_user_id=row.used_by_tg_user_id,
            )
