"""A failing store: 503 for the admin API, the mark refused with the text of the network error."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.adapters.checkin.keys import STORE
from app.core.checkin.model import Checkin
from app.core.ports import StorageUnavailable
from app.main import create_app
from app.services import override
from tests.checkin.helpers import ADMIN, ERRORS, HTMX
from tests.conftest import SettingsFactory
from tests.fakes import FakeDatabaseProbe, FixedClock, fake_overrides
from tests.html_tree import parse


class BrokenStore:
    """Every operation fails as an unreachable database does."""

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        def fail(*args: object, **kwargs: object) -> None:
            raise StorageUnavailable(name)

        return fail


@pytest.fixture
def broken(make_settings: SettingsFactory) -> Iterator[TestClient]:
    app = create_app(
        make_settings(),
        db_probe=FakeDatabaseProbe(),
        overrides=[*fake_overrides(clock=FixedClock()), override(STORE, BrokenStore())],  # type: ignore[arg-type]
    )
    with TestClient(app, base_url="https://testserver") as client:
        yield client


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/admin/checkins", {"lesson_date": "2026-11-02"}),
        ("POST", "/admin/checkins/1/close", None),
        ("GET", "/admin/checkins", None),
        ("GET", "/admin/checkins/1", None),
        ("PUT", "/admin/groups/cbs-2026-10/members", {"emails": ["a@example.com"]}),
        ("GET", "/admin/groups", None),
    ],
)
def test_a_storage_failure_is_503(
    broken: TestClient, method: str, path: str, body: dict[str, object] | None
) -> None:
    response = broken.request(method, path, json=body, headers=ADMIN)

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert response.headers["cache-control"] == "no-store"


def test_a_storage_failure_on_a_mark_shows_the_error_of_the_network(broken: TestClient) -> None:
    response = broken.post(
        "/checkin", data={"code": "AB2C", "email": "one@example.com"}, headers=HTMX
    )

    assert response.status_code == 503
    shown = parse(response.text).find("div", id="checkin").text()
    assert ERRORS["Помилка мережі або сервера"] in shown


def test_a_checkin_knows_when_it_is_open() -> None:
    opened = datetime(2026, 11, 2, 16, 0, tzinfo=UTC)
    checkin = Checkin(1, "AB2C", date(2026, 11, 2), None, opened, opened + timedelta(minutes=20))

    assert not checkin.is_open(opened - timedelta(microseconds=1))
    assert checkin.is_open(opened)
    assert not checkin.is_open(opened + timedelta(minutes=20))
