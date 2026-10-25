"""Fixtures of the slice «жива статистика»: the application on the test database with fakes."""

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.main import create_app
from app.services import Override
from tests.conftest import SettingsFactory
from tests.fakes import FakeDatabaseProbe, FixedClock, fake_overrides


@dataclass
class Site:
    client: TestClient
    clock: FixedClock


type SiteFactory = Callable[..., Site]


@pytest.fixture
def site_factory(
    make_settings: SettingsFactory, test_db_url: str, migrated_engine: Engine
) -> Iterator[SiteFactory]:
    """``site_factory(clock=…, overrides=…, **env)``: the application on the migrated test
    database."""
    clients: list[TestClient] = []

    def build(
        *, clock: FixedClock | None = None, overrides: Sequence[Override] = (), **env: str | None
    ) -> Site:
        fixed = clock if clock is not None else FixedClock()
        app = create_app(
            make_settings(DATABASE_URL=test_db_url, **env),
            db_probe=FakeDatabaseProbe(),
            overrides=[*fake_overrides(clock=fixed), *overrides],
        )
        client = TestClient(app, base_url="https://testserver")
        client.__enter__()
        clients.append(client)
        return Site(client, fixed)

    yield build
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def site(site_factory: SiteFactory) -> Site:
    return site_factory()
