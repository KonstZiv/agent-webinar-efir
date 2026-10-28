"""Revision 0003: the tables of the attendance, their constraints, the cascade of an unsubscribe.

The columns and constraints follow the task's appendix А (docs/requirements.md, section 9а).
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import DataError, IntegrityError

from app.adapters.db.participants import SqlParticipantStore
from tests.conftest import ParticipantFactory
from tests.database import downgrade, migrate

NOW = datetime(2026, 11, 2, 16, 0, tzinfo=UTC)
TABLES = {"participant_groups", "checkins", "attendance"}


def run(engine: Engine, sql: str, **values: object) -> None:
    with engine.begin() as connection:
        connection.execute(text(sql), values)


def add_checkin(engine: Engine, group: str | None = "cbs-2026-10") -> int:
    with engine.begin() as connection:
        return int(
            connection.execute(
                text(
                    "INSERT INTO checkins (code, lesson_date, group_code, opened_at, closes_at)"
                    " VALUES ('AB2C', :day, :group, :opened, :closes) RETURNING id"
                ),
                {
                    "day": date(2026, 11, 2),
                    "group": group,
                    "opened": NOW,
                    "closes": NOW + timedelta(hours=1),
                },
            ).scalar_one()
        )


def add_mark(engine: Engine, checkin_id: int, participant_id: int, **values: object) -> None:
    fields = {"source": "site", "rating": None, "question": None, **values}
    run(
        engine,
        "INSERT INTO attendance (checkin_id, participant_id, source, rating, question,"
        " created_at, updated_at) VALUES (:checkin, :participant, :source, :rating, :question,"
        " :at, :at)",
        checkin=checkin_id,
        participant=participant_id,
        at=NOW,
        **fields,
    )


def columns(engine: Engine, table: str) -> dict[str, tuple[str, bool]]:
    with engine.connect() as connection:
        found = inspect(connection).get_columns(table)
    return {
        c["name"]: (
            "TIMESTAMP WITH TIME ZONE" if getattr(c["type"], "timezone", False) else str(c["type"]),
            bool(c["nullable"]),
        )
        for c in found
    }


def test_the_columns_follow_the_appendix(migrated_engine: Engine) -> None:
    assert columns(migrated_engine, "participant_groups") == {
        "id": ("BIGINT", False),
        "participant_id": ("BIGINT", False),
        "group_code": ("VARCHAR(32)", False),
        "assigned_at": ("TIMESTAMP WITH TIME ZONE", False),
    }
    assert columns(migrated_engine, "checkins") == {
        "id": ("BIGINT", False),
        "code": ("VARCHAR(8)", False),
        "lesson_date": ("DATE", False),
        "group_code": ("VARCHAR(32)", True),
        "opened_at": ("TIMESTAMP WITH TIME ZONE", False),
        "closes_at": ("TIMESTAMP WITH TIME ZONE", False),
        "created_at": ("TIMESTAMP WITH TIME ZONE", False),
    }
    assert columns(migrated_engine, "attendance") == {
        "id": ("BIGINT", False),
        "checkin_id": ("BIGINT", False),
        "participant_id": ("BIGINT", False),
        "source": ("VARCHAR(8)", False),
        "rating": ("SMALLINT", True),
        "question": ("VARCHAR(500)", True),
        "created_at": ("TIMESTAMP WITH TIME ZONE", False),
        "updated_at": ("TIMESTAMP WITH TIME ZONE", False),
    }


def test_the_indexes_and_the_uniques(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        inspector = inspect(connection)
        indexed = {
            table: {tuple(i["column_names"]) for i in inspector.get_indexes(table)}
            for table in TABLES
        }
        unique = {
            table: {tuple(u["column_names"]) for u in inspector.get_unique_constraints(table)}
            for table in TABLES
        }

    assert {("participant_id",), ("group_code",)} <= indexed["participant_groups"]
    assert ("code",) in indexed["checkins"]
    assert {("checkin_id",), ("participant_id",)} <= indexed["attendance"]
    assert ("participant_id", "group_code") in unique["participant_groups"]
    assert ("checkin_id", "participant_id") in unique["attendance"]


def test_downgrade_to_0002_removes_the_tables(
    fresh_engine: Engine,
) -> None:
    migrate(fresh_engine, "head")

    downgrade(fresh_engine, "0002")

    with fresh_engine.connect() as connection:
        assert not TABLES & set(inspect(connection).get_table_names())


@pytest.mark.parametrize("code", ["CBS", "x", "a_b", "a" * 33, "кбс"])
def test_a_group_code_must_be_lower_case_latin_digits_and_hyphens(
    migrated_engine: Engine, participant_factory: ParticipantFactory, code: str
) -> None:
    participant = participant_factory()

    with pytest.raises((IntegrityError, DataError)):
        run(
            migrated_engine,
            "INSERT INTO participant_groups (participant_id, group_code, assigned_at)"
            " VALUES (:id, :code, :at)",
            id=participant.id,
            code=code,
            at=NOW,
        )
    with pytest.raises((IntegrityError, DataError)):
        add_checkin(migrated_engine, group=code)


def test_a_participant_is_in_a_group_once(
    migrated_engine: Engine, participant_factory: ParticipantFactory
) -> None:
    participant = participant_factory()
    insert = (
        "INSERT INTO participant_groups (participant_id, group_code, assigned_at)"
        " VALUES (:id, 'cbs-2026-10', :at)"
    )
    run(migrated_engine, insert, id=participant.id, at=NOW)

    with pytest.raises(IntegrityError):
        run(migrated_engine, insert, id=participant.id, at=NOW)


def test_a_checkin_closes_after_it_opens(migrated_engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        run(
            migrated_engine,
            "INSERT INTO checkins (code, lesson_date, opened_at, closes_at)"
            " VALUES ('AB2C', :day, :at, :at)",
            day=date(2026, 11, 2),
            at=NOW,
        )


def test_a_checkin_may_have_no_group(migrated_engine: Engine) -> None:
    assert add_checkin(migrated_engine, group=None) > 0


@pytest.mark.parametrize(
    "values",
    [{"source": "email"}, {"rating": 0}, {"rating": 6}, {"question": "я" * 501}],
)
def test_a_mark_is_checked(
    migrated_engine: Engine, participant_factory: ParticipantFactory, values: dict[str, object]
) -> None:
    participant = participant_factory()
    checkin = add_checkin(migrated_engine)

    with pytest.raises((IntegrityError, DataError)):
        add_mark(migrated_engine, checkin, participant.id, **values)


@pytest.mark.parametrize("source", ["site", "telegram"])
def test_a_mark_has_one_row_per_person_and_checkin(
    migrated_engine: Engine, participant_factory: ParticipantFactory, source: str
) -> None:
    participant = participant_factory()
    checkin = add_checkin(migrated_engine)
    add_mark(migrated_engine, checkin, participant.id, source=source, rating=5)

    with pytest.raises(IntegrityError):
        add_mark(migrated_engine, checkin, participant.id)


def test_an_unsubscribe_removes_the_marks_and_the_groups_of_the_participant(
    migrated_engine: Engine, participant_factory: ParticipantFactory
) -> None:
    leaving = participant_factory("leaving@example.com")
    staying = participant_factory("staying@example.com")
    checkin = add_checkin(migrated_engine)
    for participant in (leaving, staying):
        add_mark(migrated_engine, checkin, participant.id, rating=4, question="?")
        run(
            migrated_engine,
            "INSERT INTO participant_groups (participant_id, group_code, assigned_at)"
            " VALUES (:id, 'cbs-2026-10', :at)",
            id=participant.id,
            at=NOW,
        )

    assert SqlParticipantStore(migrated_engine).remove_by_unsubscribe_id(leaving.unsubscribe_id)

    with migrated_engine.connect() as connection:
        marks = connection.execute(text("SELECT participant_id FROM attendance")).scalars().all()
        groups = (
            connection.execute(text("SELECT participant_id FROM participant_groups"))
            .scalars()
            .all()
        )
        checkins = connection.execute(text("SELECT count(*) FROM checkins")).scalar_one()
    assert marks == [staying.id]
    assert groups == [staying.id]
    assert checkins == 1


def test_deleting_a_checkin_removes_its_marks(
    migrated_engine: Engine, participant_factory: ParticipantFactory
) -> None:
    participant = participant_factory()
    checkin = add_checkin(migrated_engine)
    add_mark(migrated_engine, checkin, participant.id)

    run(migrated_engine, "DELETE FROM checkins WHERE id = :id", id=checkin)

    with migrated_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM attendance")).scalar_one() == 0
