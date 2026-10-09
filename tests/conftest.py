"""Shared fixtures: settings from environment variables and a disposable PostgreSQL database."""

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import make_url, text
from sqlalchemy.exc import OperationalError

from app.adapters.db.engine import make_engine
from app.settings import Settings, load_settings, normalize_database_url

# Every environment variable read by ``Settings`` (kept in sync by tests/test_settings.py).
ALL_SETTING_NAMES = (
    "DATABASE_URL",
    "REDIRECT_BASE_URL",
    "INDEXING_ENABLED",
    "GA4_MEASUREMENT_ID",
    "TURNSTILE_SITE_KEY",
    "TURNSTILE_SECRET_KEY",
    "TURNSTILE_ALLOWED_HOSTNAMES",
    "RAILWAY_GIT_COMMIT_SHA",
)

# Fake values for the required variables; each one is unique so tests can prove that error
# messages never echo them.
REQUIRED_ENV = {
    "DATABASE_URL": "postgresql://app:sentinel-db-password@localhost:5432/sentinel_db",
}
# Fake values for optional variables that are secret or identify an account.
OPTIONAL_ENV = {
    "GA4_MEASUREMENT_ID": "G-SENTINEL01",
    "TURNSTILE_SITE_KEY": "sentinel-turnstile-site-key",
    "TURNSTILE_SECRET_KEY": "sentinel-turnstile-secret-key",
}
SENTINEL_VALUES = {**REQUIRED_ENV, **OPTIONAL_ENV}

# Local server from compose.yaml (host port 55433, not the shared default 5432).
DEFAULT_PG_SERVER_URL = "postgresql://app@localhost:55433/app"
TEST_DB_NAME = "app_test"

type SettingsFactory = Callable[..., Settings]

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _run_from_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """The app reads docs/ from the working directory, as on Railway (/app)."""
    monkeypatch.chdir(REPO_ROOT)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never reach Turnstile or Google: real HTTP transports refuse to send.

    ``httpx.MockTransport`` and ``TestClient`` use their own transports and keep working.
    """

    def refuse(_: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        raise RuntimeError(f"tests must not reach the network ({request.url.host})")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Remove every settings variable inherited from the shell."""
    for name in ALL_SETTING_NAMES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def set_env(clean_env: pytest.MonkeyPatch) -> Callable[..., None]:
    """Set the required variables plus overrides; ``None`` removes a variable."""

    def apply(**overrides: str | None) -> None:
        for name, value in {**REQUIRED_ENV, **overrides}.items():
            if value is None:
                clean_env.delenv(name, raising=False)
            else:
                clean_env.setenv(name, value)

    return apply


@pytest.fixture
def make_settings(set_env: Callable[..., None]) -> SettingsFactory:
    """Build ``Settings`` the same way the application does: from the environment."""

    def factory(**overrides: str | None) -> Settings:
        set_env(**overrides)
        return load_settings()

    return factory


@pytest.fixture(scope="session")
def pg_server_url() -> str:
    """URL of a reachable PostgreSQL server; skipped locally and fatal in CI when absent."""
    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_PG_SERVER_URL)
    engine = make_engine(normalize_database_url(url))
    try:
        with engine.connect():
            pass
    except OperationalError:
        if os.environ.get("CI") == "true":
            pytest.fail("PostgreSQL from TEST_DATABASE_URL is not reachable in CI")
        pytest.skip("PostgreSQL is not reachable: run `docker compose up -d`")
    finally:
        engine.dispose()
    return url


@pytest.fixture(scope="session")
def test_db_url(pg_server_url: str) -> Iterator[str]:
    """A fresh, empty database for the test session; dropped afterwards."""
    server_url = make_url(normalize_database_url(pg_server_url))
    admin_url = server_url.set(database="postgres").render_as_string(hide_password=False)
    engine = make_engine(admin_url)
    admin = engine.execution_options(isolation_level="AUTOCOMMIT")
    drop = text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)')
    with admin.connect() as connection:
        connection.execute(drop)
        connection.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    try:
        yield server_url.set(database=TEST_DB_NAME).render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            connection.execute(drop)
        engine.dispose()
