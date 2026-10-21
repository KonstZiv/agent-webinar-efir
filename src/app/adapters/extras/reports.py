"""``ReportStore`` on the shared tables ``participants`` and ``emails`` (v1 writes them too).

Read-only. Each report is one statement in one time-bounded transaction (``transaction``): one
snapshot, so the numbers agree while people register, and a failure becomes a ``StorageError``.
The rule of a failed email reads the database clock, as v1 and «реєстрація і лист» do; the
statistics count the failed invitations only, those the operator's retry sends.
"""

from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, Engine, and_, func, or_, select

from app.adapters.db.models import EmailRecord, Participant
from app.adapters.db.transaction import transaction
from app.core.extras.ports import Counts, ExportRow, Stats

_LINKED = Participant.tg_user_id.is_not(None)
# The kind ``POST /admin/emails/retry`` sends again; v2 never sends v1's ``confirmation``.
_INVITATION = "lesson_invitation"


def _failed_invitation(stale_after: timedelta) -> ColumnElement[bool]:
    """An invitation ``failed``, or ``pending`` past ``stale_after`` (its process died), unless
    scheduled ahead.

    docs/requirements.md, sections 6 and 8; ``updated_at`` and ``scheduled_at`` by the database
    clock.
    """
    stale = EmailRecord.updated_at < func.now() - stale_after
    due = or_(EmailRecord.scheduled_at.is_(None), EmailRecord.scheduled_at <= func.now())
    failed = or_(EmailRecord.status == "failed", and_(EmailRecord.status == "pending", stale))
    return and_(EmailRecord.kind == _INVITATION, failed, due)


class SqlReportStore:
    """``ReportStore`` backed by a SQLAlchemy engine."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def counts(self) -> Counts:
        statement = select(func.count(), func.count().filter(_LINKED)).select_from(Participant)
        with transaction(self._engine, "count participants") as session:
            registered, linked = session.execute(statement).one()
        return Counts(registered=registered, telegram_linked=linked)

    def stats(self, registered_since: datetime, stale_after: timedelta) -> Stats:
        failed = (
            select(func.count())
            .select_from(EmailRecord)
            .where(_failed_invitation(stale_after))
            .scalar_subquery()
        )
        statement = select(
            func.count(),
            func.count().filter(Participant.registered_at >= registered_since),
            failed,
            func.count().filter(_LINKED),
            func.count().filter(Participant.channel_member.is_(True)),
        ).select_from(Participant)
        with transaction(self._engine, "count statistics") as session:
            total, last_24h, failed_emails, linked, members = session.execute(statement).one()
        return Stats(
            total=total,
            last_24h=last_24h,
            failed_emails=failed_emails,
            telegram_linked=linked,
            channel_members=members,
        )

    def export_rows(self) -> list[ExportRow]:
        statement = select(
            Participant.email,
            Participant.registered_at,
            Participant.origin,
            _LINKED.label("telegram_linked"),
            Participant.channel_member,
            Participant.level,
            Participant.utm_source,
            Participant.utm_medium,
            Participant.utm_campaign,
            Participant.utm_content,
        ).order_by(Participant.registered_at, Participant.id)
        with transaction(self._engine, "export participants") as session:
            return [ExportRow(**row._asdict()) for row in session.execute(statement)]
