"""``SqlLevelStore`` on the test database: only ``level`` changes, a repeat overwrites."""

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.adapters.db.models import Participant
from app.adapters.quiz.levels import SqlLevelStore
from tests.conftest import ParticipantFactory


def level_of(engine: Engine, participant_id: int) -> str | None:
    with Session(engine) as session:
        return session.scalar(select(Participant.level).where(Participant.id == participant_id))


def test_the_level_is_written_and_overwritten(
    migrated_engine: Engine, participant_factory: ParticipantFactory
) -> None:
    mine = participant_factory("mine@example.com")
    other = participant_factory("other@example.com", level="level2")
    store = SqlLevelStore(migrated_engine)

    assert store.set_level("mine@example.com", "level1_plus") is True
    assert store.set_level("mine@example.com", "level1") is True

    assert level_of(migrated_engine, mine.id) == "level1"
    assert level_of(migrated_engine, other.id) == "level2"


def test_an_unknown_address_is_not_written(migrated_engine: Engine) -> None:
    assert SqlLevelStore(migrated_engine).set_level("nobody@example.com", "level1") is False
