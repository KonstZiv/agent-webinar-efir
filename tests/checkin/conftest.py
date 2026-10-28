"""Fixtures of the slice «відмітка присутності»: the application on the migrated test database.

The participants and the check-ins are real rows; the clock and the outside services are fakes.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.main import create_app
from tests.checkin.helpers import Site
from tests.conftest import SettingsFactory
from tests.fakes import FakeDatabaseProbe, FixedClock, fake_overrides


@pytest.fixture
def site(
    make_settings: SettingsFactory, test_db_url: str, migrated_engine: Engine
) -> Iterator[Site]:
    clock = FixedClock()
    app = create_app(
        make_settings(DATABASE_URL=test_db_url),
        db_probe=FakeDatabaseProbe(),
        overrides=fake_overrides(clock=clock),
    )
    with TestClient(app, base_url="https://testserver") as client:
        yield Site(client, migrated_engine, clock)
