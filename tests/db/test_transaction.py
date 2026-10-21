"""``transaction``: every database failure becomes an exception of the port, logged by class only.

``StorageUnavailable`` means the database did not answer; ``StorageConflict`` — the data broke a
constraint; any other failure is a ``StorageError``. Driver messages may hold personal data and
statement values, so neither reaches the log or the raised exception.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, insert, select, text

from app.adapters.db.engine import make_engine
from app.adapters.db.models import LinkToken as LinkTokenRow
from app.adapters.db.models import Participant as ParticipantRow
from app.adapters.db.transaction import transaction
from app.core.ports import StorageConflict, StorageError, StorageUnavailable
from tests.conftest import ParticipantFactory

EMAIL = "visitor@example.com"
NOW = datetime(2026, 10, 20, 17, 0, tzinfo=UTC)


def participant_row(email: str = EMAIL) -> dict[str, object]:
    return {
        "email": email,
        "unsubscribe_id": uuid.uuid4(),
        "registered_at": NOW,
        "consent_version": "consent-v1",
        "consent_at": NOW,
    }


def test_both_kinds_are_storage_errors() -> None:
    assert issubclass(StorageUnavailable, StorageError)
    assert issubclass(StorageConflict, StorageError)
    assert not issubclass(StorageConflict, StorageUnavailable)


def test_a_duplicate_key_is_a_conflict(
    migrated_engine: Engine, participant_factory: ParticipantFactory
) -> None:
    participant_factory(EMAIL)

    with pytest.raises(StorageConflict), transaction(migrated_engine, "add") as session:
        session.execute(insert(ParticipantRow).values(participant_row()))


def test_a_missing_participant_is_a_conflict(migrated_engine: Engine) -> None:
    row = {
        "participant_id": 404,
        "token": "Abc_def-0123456789abcdefghijklmnopqrstuv",
        "source": "screen",
        "created_at": NOW,
        "expires_at": NOW,
    }

    with pytest.raises(StorageConflict), transaction(migrated_engine, "add") as session:
        session.execute(insert(LinkTokenRow).values(row))


def test_a_failed_check_is_a_conflict(migrated_engine: Engine) -> None:
    """A slice's bug (an address not normalised) is not an outage of the database."""
    with pytest.raises(StorageConflict), transaction(migrated_engine, "add") as session:
        session.execute(insert(ParticipantRow).values(participant_row("Visitor@Example.com")))


@pytest.mark.parametrize(
    "statement",
    [
        pytest.param("SELECT :value AS value, 1 / 0", id="data error"),
        pytest.param("SELECT :value FROM no_such_table", id="programming error"),
    ],
)
def test_other_failures_are_storage_errors_and_hide_the_data(
    migrated_engine: Engine, statement: str, caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(StorageError) as failure, transaction(migrated_engine, "count") as session:
        session.execute(text(statement), {"value": EMAIL})

    assert type(failure.value) is StorageError
    assert EMAIL not in str(failure.value)
    assert failure.value.__cause__ is None
    assert "«count»" in caplog.text
    assert EMAIL not in caplog.text


def test_no_row_where_one_was_expected_is_a_storage_error(migrated_engine: Engine) -> None:
    with pytest.raises(StorageError), transaction(migrated_engine, "find") as session:
        session.scalars(select(ParticipantRow).where(ParticipantRow.email == EMAIL)).one()


def test_the_log_names_the_operation_and_the_error_class_only(
    migrated_engine: Engine,
    participant_factory: ParticipantFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    participant_factory(EMAIL)

    with pytest.raises(StorageConflict), transaction(migrated_engine, "add") as session:
        session.execute(insert(ParticipantRow).values(participant_row()))

    assert [record.getMessage() for record in caplog.records] == [
        "Storage operation «add» failed: IntegrityError"
    ]


def test_an_unreachable_database_is_unavailable() -> None:
    engine = make_engine("postgresql+psycopg://app@127.0.0.1:1/unreachable")
    try:
        with pytest.raises(StorageUnavailable), transaction(engine, "find"):
            pass
    finally:
        engine.dispose()
