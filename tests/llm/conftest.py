"""Fixtures of the slice «llm»: the application with the bot and the LLM settings, a fake model."""

from collections.abc import Callable, Iterator, Sequence

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.adapters.llm.keys import MODEL
from app.core.llm.ports import ModelReply
from app.main import create_app
from app.services import Override, override
from tests.conftest import LLM_ENV, SettingsFactory
from tests.fakes import FakeDatabaseProbe, FakeMessenger, FixedClock, fake_overrides
from tests.llm.helpers import BOT_SITE_ENV, FakeModel, LlmSite

type LlmSiteFactory = Callable[..., LlmSite]


@pytest.fixture
def llm_site_factory(
    make_settings: SettingsFactory,
    test_db_url: str,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[LlmSiteFactory]:
    """``llm_site_factory(script=…, enabled=True, limits=…, overrides=…, **env)``.

    The application runs on the migrated test database with the bot settings; the language
    model is a ``FakeModel`` with the given script. ``limits`` are ``LLM_*`` variables of the
    slice (``{"LLM_MAX_CHARS": "50"}``). ``enabled=False`` leaves ``LLM_ENABLED`` off.
    """
    clients: list[TestClient] = []

    def build(
        *,
        script: Sequence[ModelReply | Exception] | None = None,
        enabled: bool = True,
        limits: dict[str, str] | None = None,
        overrides: Sequence[Override] = (),
        **env: str | None,
    ) -> LlmSite:
        for name, value in (limits or {}).items():
            monkeypatch.setenv(name, value)
        model = FakeModel(list(script)) if script is not None else FakeModel()
        messenger, clock = FakeMessenger(), FixedClock()
        group = LLM_ENV if enabled else {}
        settings = make_settings(DATABASE_URL=test_db_url, **{**BOT_SITE_ENV, **group, **env})
        app = create_app(
            settings,
            db_probe=FakeDatabaseProbe(),
            overrides=[
                *fake_overrides(clock=clock, messenger=messenger),
                override(MODEL, model),
                *overrides,
            ],
        )
        client = TestClient(app, base_url="https://testserver")
        client.__enter__()
        clients.append(client)
        return LlmSite(client, migrated_engine, messenger, clock, model)

    yield build
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def llm_site(llm_site_factory: LlmSiteFactory) -> LlmSite:
    return llm_site_factory()
