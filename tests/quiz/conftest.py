"""Fixtures of the slice «мінітест рівня»: the application with a fake store of levels."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app.adapters.quiz.keys import LEVELS
from app.main import create_app
from app.services import override
from tests.conftest import SettingsFactory
from tests.fakes import FakeDatabaseProbe, FixedClock, fake_overrides
from tests.quiz.helpers import FakeLevelStore


@dataclass
class Site:
    client: TestClient
    store: FakeLevelStore
    clock: FixedClock

    def ticket(self, email: str) -> str:
        """The ticket the success screen would hand out, taken from the template global."""
        return self.client.app.state.container.templates.env.globals["quiz"].ticket(email)  # type: ignore[attr-defined,no-any-return]


@pytest.fixture
def site(make_settings: SettingsFactory) -> Iterator[Site]:
    store = FakeLevelStore()
    clock = FixedClock()
    app = create_app(
        make_settings(),
        db_probe=FakeDatabaseProbe(),
        overrides=[*fake_overrides(clock=clock), override(LEVELS, store)],
    )
    with TestClient(app, base_url="https://testserver") as client:
        yield Site(client, store, clock)


type SiteFactory = Callable[[], Site]
