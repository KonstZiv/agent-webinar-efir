"""The application provides the shared stores; the engine is created only when one is used."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine

from app import main
from app.core.entities import NewParticipant
from app.main import create_app
from app.services import LINK_TOKENS, PARTICIPANTS
from tests.conftest import SettingsFactory
from tests.fakes import FakeDatabaseProbe

NOW = datetime(2026, 10, 20, 17, 0, tzinfo=UTC)


def test_the_stores_work_on_the_application_database(
    migrated_engine: Engine, test_db_url: str, make_settings: SettingsFactory
) -> None:
    services = create_app(make_settings(DATABASE_URL=test_db_url)).state.container.services
    participants = services.get(PARTICIPANTS)

    stored, created = participants.add_if_absent(
        NewParticipant("store@example.com", uuid.uuid4(), NOW, "consent-v1", NOW)
    )

    assert created is True
    assert participants.by_id(stored.id) == stored
    assert services.get(LINK_TOKENS).find("no-such-token") is None


def test_no_engine_until_a_store_is_used(
    make_settings: SettingsFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``create_app(settings, db_probe=…)`` in tests creates no engine and reaches no database."""
    created: list[str] = []
    real = main.make_engine
    monkeypatch.setattr(main, "make_engine", lambda url: created.append(url) or real(url))

    app = create_app(make_settings(), db_probe=FakeDatabaseProbe())
    assert created == []

    app.state.container.services.get(PARTICIPANTS)
    assert len(created) == 1
