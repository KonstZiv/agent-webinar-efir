"""Fixtures of the slice «бот»: the application with the bot settings, with or without database."""

from collections.abc import Callable, Iterator, Sequence

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.main import create_app
from app.services import Override
from tests.bot.helpers import BOT_SITE_ENV, BotSite
from tests.conftest import SettingsFactory
from tests.fakes import FakeDatabaseProbe, FakeMessenger, FixedClock, fake_overrides

type BotSiteFactory = Callable[..., BotSite]
type ClientFactory = Callable[..., TestClient]


@pytest.fixture
def bot_site_factory(
    make_settings: SettingsFactory, test_db_url: str, migrated_engine: Engine
) -> Iterator[BotSiteFactory]:
    """``bot_site_factory(messenger=…, clock=…, overrides=…, **env)``.

    The application runs on the migrated test database with the bot settings and
    ``MATERIALS_SLUG``; the variables in ``env`` come on top (``None`` removes one).
    """
    clients: list[TestClient] = []

    def build(
        *,
        messenger: FakeMessenger | None = None,
        clock: FixedClock | None = None,
        overrides: Sequence[Override] = (),
        **env: str | None,
    ) -> BotSite:
        telegram = messenger if messenger is not None else FakeMessenger()
        fixed = clock if clock is not None else FixedClock()
        settings = make_settings(DATABASE_URL=test_db_url, **{**BOT_SITE_ENV, **env})
        app = create_app(
            settings,
            db_probe=FakeDatabaseProbe(),
            overrides=[*fake_overrides(clock=fixed, messenger=telegram), *overrides],
        )
        client = TestClient(app, base_url="https://testserver")
        client.__enter__()
        clients.append(client)
        return BotSite(client, migrated_engine, settings, telegram, fixed)

    yield build
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def bot_site(bot_site_factory: BotSiteFactory) -> BotSite:
    return bot_site_factory()


@pytest.fixture
def client_factory(make_settings: SettingsFactory) -> Iterator[ClientFactory]:
    """``client_factory(messenger=…, **env)``: the application with the bot settings and no
    database, started (its start-up actions have run)."""
    clients: list[TestClient] = []

    def build(*, messenger: FakeMessenger | None = None, **env: str | None) -> TestClient:
        app = create_app(
            make_settings(**{**BOT_SITE_ENV, **env}),
            db_probe=FakeDatabaseProbe(),
            overrides=fake_overrides(messenger=messenger),
        )
        client = TestClient(app, base_url="https://testserver")
        client.__enter__()
        clients.append(client)
        return client

    yield build
    for client in clients:
        client.__exit__(None, None, None)
