"""The shared participant factory fills every table of the model (tests/factories.py)."""

from sqlalchemy import Engine, text

from app.core.entities import TelegramAccount
from tests.conftest import ParticipantFactory


def test_a_participant_with_rows_in_every_table(
    participant_factory: ParticipantFactory, migrated_engine: Engine
) -> None:
    created = participant_factory(
        "factory@example.com",
        telegram=TelegramAccount(42, "factory_user"),
        channel_member=True,
        emails={"confirmation": "sent", "lesson_invitation": "failed"},
        link_tokens=["screen", "email"],
        clicks=["lesson"],
    )

    with migrated_engine.connect() as connection:
        row = connection.execute(
            text("SELECT email, origin, tg_user_id, tg_username, channel_member FROM participants")
        ).one()
        counts = {
            table: connection.execute(
                text(f"SELECT count(*) FROM {table} WHERE participant_id = :id"),
                {"id": created.id},
            ).scalar_one()
            for table in ("emails", "link_tokens", "clicks")
        }
    assert tuple(row) == ("factory@example.com", "v2", 42, "factory_user", True)
    assert counts == {"emails": 2, "link_tokens": 2, "clicks": 1}
    assert len(created.link_tokens) == 2


def test_a_participant_as_v1_stores_it(
    participant_factory: ParticipantFactory, migrated_engine: Engine
) -> None:
    created = participant_factory(origin=None)

    with migrated_engine.connect() as connection:
        origin = connection.execute(
            text("SELECT origin FROM participants WHERE id = :id"), {"id": created.id}
        ).scalar_one()
    assert origin is None
    assert created.email.endswith("@example.com")
