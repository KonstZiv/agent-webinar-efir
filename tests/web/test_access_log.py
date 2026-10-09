"""The uvicorn access log never carries a secret token from a path under a token prefix."""

import logging

import pytest

from app.adapters.web import token_paths
from app.adapters.web.access_log import ACCESS_LOGGER, MaskTokenPaths, install_access_log_filter
from app.main import create_app
from tests.conftest import SettingsFactory
from tests.fakes import FakeDatabaseProbe

PREFIXES = ("/t/", "/confirm/")
TOKEN = "0123456789abcdef0123456789abcdef.kX_fckLtX_yJu1UX9FsTzHwSZ_NflbFFdeL5yZnoC8g"


def access_record(path: str) -> logging.LogRecord:
    """A record shaped like uvicorn's: client, method, path with query, version, status."""
    return logging.LogRecord(
        ACCESS_LOGGER,
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("192.0.2.10:5000", "POST", path, "1.1", 200),
        None,
    )


@pytest.mark.parametrize(
    ("path", "logged"),
    [
        (f"/t/{TOKEN}", "/t/***"),
        (f"/t/{TOKEN}?x=1", "/t/***?x=1"),
        (f"/confirm/{TOKEN}/done", "/confirm/***/done"),
        ("/t/garbage%20with%20spaces", "/t/***"),
        ("/", "/"),
        ("/privacy?secret=1", "/privacy?secret=1"),
        ("/t", "/t"),
        ("/x/t/abc", "/x/t/abc"),
    ],
)
def test_token_is_masked(path: str, logged: str) -> None:
    record = access_record(path)

    assert MaskTokenPaths(PREFIXES).filter(record) is True
    assert record.getMessage() == f'192.0.2.10:5000 - "POST {logged} HTTP/1.1" 200'


def test_without_prefixes_nothing_is_masked() -> None:
    record = access_record(f"/t/{TOKEN}")

    assert MaskTokenPaths(()).filter(record) is True
    assert TOKEN in record.getMessage()


def test_other_records_pass_unchanged() -> None:
    record = logging.LogRecord(ACCESS_LOGGER, logging.INFO, __file__, 1, "plain", None, None)

    assert MaskTokenPaths(PREFIXES).filter(record) is True
    assert record.getMessage() == "plain"


def mask_filters() -> list[MaskTokenPaths]:
    filters = logging.getLogger(ACCESS_LOGGER).filters
    return [item for item in filters if isinstance(item, MaskTokenPaths)]


@pytest.fixture
def no_access_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start from an access logger without filters; the original list returns afterwards."""
    monkeypatch.setattr(logging.getLogger(ACCESS_LOGGER), "filters", [])


@pytest.mark.usefixtures("no_access_filters")
def test_filter_is_installed_once() -> None:
    install_access_log_filter(PREFIXES)
    install_access_log_filter(PREFIXES)

    assert [item.prefixes for item in mask_filters()] == [PREFIXES]


@pytest.mark.usefixtures("no_access_filters")
def test_filter_with_other_prefixes_is_replaced() -> None:
    install_access_log_filter(("/old/",))

    install_access_log_filter(PREFIXES)

    assert [item.prefixes for item in mask_filters()] == [PREFIXES]


@pytest.mark.usefixtures("no_access_filters")
def test_prefixes_are_read_when_the_filter_is_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A filter installed earlier (by another test or app) does not freeze the prefixes."""
    install_access_log_filter()
    monkeypatch.setattr(token_paths, "TOKEN_PATH_PREFIXES", PREFIXES)

    install_access_log_filter()

    [mask] = mask_filters()
    record = access_record(f"/t/{TOKEN}")
    mask.filter(record)
    assert TOKEN not in record.getMessage()


@pytest.mark.usefixtures("no_access_filters")
def test_app_installs_the_filter_once(make_settings: SettingsFactory) -> None:
    for _ in range(2):
        create_app(make_settings(), db_probe=FakeDatabaseProbe())

    assert [item.prefixes for item in mask_filters()] == [token_paths.TOKEN_PATH_PREFIXES]


@pytest.mark.usefixtures("no_access_filters")
def test_app_masks_with_the_current_prefixes(
    make_settings: SettingsFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whatever filter an earlier app left behind, the app uses the prefixes of today."""
    install_access_log_filter(("/left-behind/",))
    monkeypatch.setattr(token_paths, "TOKEN_PATH_PREFIXES", PREFIXES)

    create_app(make_settings(), db_probe=FakeDatabaseProbe())

    [mask] = mask_filters()
    record = access_record(f"/t/{TOKEN}")
    mask.filter(record)
    assert record.getMessage() == '192.0.2.10:5000 - "POST /t/*** HTTP/1.1" 200'
