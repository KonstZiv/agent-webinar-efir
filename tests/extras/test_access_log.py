"""Polls of the counters leave no line in the uvicorn access log (docs/requirements.md, 15).

Hundreds of viewers ask for ``/counters`` every 15 seconds. The operator reads the log in
Railway when something goes wrong, live on screen: a line per poll would bury the useful ones
and show each viewer's IP address every 15 seconds (review r6, finding 2). The slice installs
its own filter; other requests are logged as before.
"""

import logging

import pytest

from app.adapters.extras.access_log import DropCounterPolls
from app.adapters.web.access_log import ACCESS_LOGGER
from app.main import create_app
from tests.conftest import SettingsFactory
from tests.fakes import FakeDatabaseProbe

CLIENT = "192.0.2.10:5000"
DROPPED = [
    ("GET", "/counters", 200),
    ("GET", "/counters", 204),
    ("GET", "/counters?t=1", 200),
    ("GET", "/counters", 503),
    ("HEAD", "/counters", 405),
]
KEPT = [
    ("GET", "/", 200),
    ("POST", "/register", 200),
    ("GET", "/admin/stats", 200),
    ("GET", "/counters/", 307),
    ("GET", "/counters-old", 404),
    ("GET", "/x/counters", 404),
]


def log_access(method: str, path: str, status: int) -> None:
    """A line as uvicorn writes one per request: client, method, path with query, version,
    status."""
    logging.getLogger(ACCESS_LOGGER).info(
        '%s - "%s %s HTTP/%s" %d', CLIENT, method, path, "1.1", status
    )


@pytest.fixture
def installed(make_settings: SettingsFactory) -> None:
    """The application is built: every slice is installed."""
    create_app(make_settings(), db_probe=FakeDatabaseProbe())


@pytest.mark.usefixtures("installed")
def test_polls_of_the_counters_leave_no_line(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER):
        for method, path, status in DROPPED:
            log_access(method, path, status)

    assert [record.getMessage() for record in caplog.records] == []


@pytest.mark.usefixtures("installed")
def test_other_requests_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER):
        for method, path, status in KEPT:
            log_access(method, path, status)

    assert [record.getMessage() for record in caplog.records] == [
        f'{CLIENT} - "{method} {path} HTTP/1.1" {status}' for method, path, status in KEPT
    ]


def test_the_filter_is_installed_once(make_settings: SettingsFactory) -> None:
    create_app(make_settings(), db_probe=FakeDatabaseProbe())
    create_app(make_settings(), db_probe=FakeDatabaseProbe())

    filters = logging.getLogger(ACCESS_LOGGER).filters
    assert len([item for item in filters if isinstance(item, DropCounterPolls)]) == 1
