"""``CheckinStore`` on the tables ``checkins``, ``attendance`` and ``participant_groups``.

Each operation is one time-bounded transaction (``transaction``): a failure becomes a
``StorageError``. The tables reference ``participants`` with ``ON DELETE CASCADE``, so an
unsubscribe removes the marks and the group membership with the participant.
"""

from collections.abc import Sequence
from datetime import date, datetime, timedelta

from sqlalchemy import Engine, case, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.adapters.db.models import Attendance, Participant, ParticipantGroup
from app.adapters.db.models import Checkin as CheckinRow
from app.adapters.db.transaction import transaction
from app.core.checkin.model import Checkin as CheckinEntity
from app.core.checkin.model import Entry, Listed, Report

# Takes turns to pick a code, so two check-ins opened at once never share one.
_CODE_LOCK = "checkin.code"


def _entity(row: CheckinRow) -> CheckinEntity:
    return CheckinEntity(
        id=row.id,
        code=row.code,
        lesson_date=row.lesson_date,
        group=row.group_code,
        opened_at=row.opened_at,
        closes_at=row.closes_at,
    )


class SqlCheckinStore:
    """``CheckinStore`` backed by a SQLAlchemy engine."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(
        self,
        code: str,
        lesson_date: date,
        group: str | None,
        opened_at: datetime,
        closes_at: datetime,
    ) -> CheckinEntity | None:
        taken = select(CheckinRow.id).where(
            CheckinRow.code == code, CheckinRow.closes_at > opened_at
        )
        with transaction(self._engine, "open check-in") as session:
            session.execute(select(func.pg_advisory_xact_lock(func.hashtext(_CODE_LOCK))))
            if session.scalars(taken.limit(1)).first() is not None:
                return None
            row = CheckinRow(
                code=code,
                lesson_date=lesson_date,
                group_code=group,
                opened_at=opened_at,
                closes_at=closes_at,
            )
            session.add(row)
            session.flush()
            return _entity(row)

    def get(self, checkin_id: int) -> CheckinEntity | None:
        with transaction(self._engine, "read check-in") as session:
            row = session.get(CheckinRow, checkin_id)
            return None if row is None else _entity(row)

    def close(self, checkin_id: int, at: datetime) -> CheckinEntity | None:
        # ``closes_at`` stays after ``opened_at`` (the table checks it) even at the same moment.
        statement = (
            update(CheckinRow)
            .where(CheckinRow.id == checkin_id, CheckinRow.closes_at > at)
            .values(closes_at=func.greatest(at, CheckinRow.opened_at + timedelta(microseconds=1)))
        )
        with transaction(self._engine, "close check-in") as session:
            session.execute(statement)
            row = session.get(CheckinRow, checkin_id, populate_existing=True)
            return None if row is None else _entity(row)

    def find_open(self, code: str, at: datetime) -> CheckinEntity | None:
        statement = (
            select(CheckinRow)
            .where(CheckinRow.code == code, CheckinRow.opened_at <= at, CheckinRow.closes_at > at)
            .order_by(CheckinRow.id.desc())
            .limit(1)
        )
        with transaction(self._engine, "find open check-in") as session:
            row = session.scalars(statement).first()
            return None if row is None else _entity(row)

    def listed(self) -> list[Listed]:
        statement = (
            select(CheckinRow, func.count(Attendance.id))
            .outerjoin(Attendance, Attendance.checkin_id == CheckinRow.id)
            .group_by(CheckinRow.id)
            .order_by(CheckinRow.id.desc())
        )
        with transaction(self._engine, "list check-ins") as session:
            return [Listed(_entity(row), count) for row, count in session.execute(statement)]

    def report(self, checkin_id: int) -> Report | None:
        statement = (
            select(
                Participant.email,
                Attendance.source,
                Attendance.rating,
                Attendance.question,
                Attendance.created_at,
            )
            .join(Participant, Participant.id == Attendance.participant_id)
            .where(Attendance.checkin_id == checkin_id)
            .order_by(Attendance.created_at, Attendance.id)
        )
        with transaction(self._engine, "report check-in") as session:
            row = session.get(CheckinRow, checkin_id)
            if row is None:
                return None
            entries = tuple(Entry(*found) for found in session.execute(statement))
            checkin = _entity(row)
        ratings = {number: 0 for number in range(1, 6)}
        for entry in entries:
            if entry.rating is not None:
                ratings[entry.rating] += 1
        return Report(checkin, ratings, entries)

    def mark(
        self,
        checkin_id: int,
        participant_id: int,
        source: str,
        rating: int | None,
        question: str | None,
        at: datetime,
    ) -> None:
        insertion = insert(Attendance).values(
            checkin_id=checkin_id,
            participant_id=participant_id,
            source=source,
            rating=rating,
            question=question,
            created_at=at,
            updated_at=at,
        )
        given = insertion.excluded
        statement = insertion.on_conflict_do_update(
            index_elements=[Attendance.checkin_id, Attendance.participant_id],
            set_={
                "rating": func.coalesce(given.rating, Attendance.rating),
                "question": func.coalesce(given.question, Attendance.question),
                "updated_at": case(
                    (given.rating.is_not(None) | given.question.is_not(None), at),
                    else_=Attendance.updated_at,
                ),
            },
        )
        with transaction(self._engine, "mark attendance") as session:
            session.execute(statement)

    def assign(self, group: str, emails: Sequence[str], at: datetime) -> tuple[int, list[str]]:
        if not emails:
            return 0, []
        with transaction(self._engine, "assign group") as session:
            found = dict(self._ids(session, emails))
            added = 0
            if found:
                rows = [
                    {"participant_id": participant_id, "group_code": group, "assigned_at": at}
                    for participant_id in found.values()
                ]
                statement = (
                    insert(ParticipantGroup)
                    .values(rows)
                    .on_conflict_do_nothing(
                        index_elements=[
                            ParticipantGroup.participant_id,
                            ParticipantGroup.group_code,
                        ]
                    )
                    .returning(ParticipantGroup.id)
                )
                added = len(session.scalars(statement).all())
        return added, [email for email in emails if email not in found]

    @staticmethod
    def _ids(session: Session, emails: Sequence[str]) -> list[tuple[str, int]]:
        statement = select(Participant.email, Participant.id).where(Participant.email.in_(emails))
        return [(email, participant_id) for email, participant_id in session.execute(statement)]

    def group_sizes(self) -> dict[str, int]:
        statement = (
            select(ParticipantGroup.group_code, func.count())
            .group_by(ParticipantGroup.group_code)
            .order_by(ParticipantGroup.group_code)
        )
        with transaction(self._engine, "count groups") as session:
            return {code: count for code, count in session.execute(statement)}
