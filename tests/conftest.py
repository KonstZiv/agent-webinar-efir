"""Shared fixtures of the foundation and every slice (docs/requirements.md, section 12).

Settings from environment variables; a disposable PostgreSQL database migrated by Alembic; a
participant with rows in every table. Fake ports live in tests/fakes.py.
"""

import functools
import ipaddress
import os
import socket
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import Engine, make_url, text
from sqlalchemy.exc import OperationalError

from app.adapters.db.engine import make_engine
from app.settings import Settings, load_settings, normalize_database_url
from tests.database import disposable_engine, migrate, reset_schema
from tests.factories import CreatedParticipant, add_participant

# Every environment variable read by ``Settings`` (kept in sync by tests/test_settings.py).
ALL_SETTING_NAMES = (
    "DATABASE_URL",
    "REDIRECT_BASE_URL",
    "INDEXING_ENABLED",
    "GA4_MEASUREMENT_ID",
    "TURNSTILE_SITE_KEY",
    "TURNSTILE_SECRET_KEY",
    "TURNSTILE_ALLOWED_HOSTNAMES",
    "SITE_MODE",
    "PUBLIC_BASE_URL",
    "EVENT_START",
    "EVENT_END",
    "LESSON_START",
    "LESSON_END",
    "STREAM_URL",
    "LESSON_URL",
    "COURSE_URL",
    "RECORDING_YOUTUBE_ID",
    "RESEND_API_KEY",
    "SENDER_EMAIL",
    "UNSUBSCRIBE_SECRET",
    "ADMIN_TOKEN",
    "REGISTRATION_ALLOWLIST",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_BOT_USERNAME",
    "TELEGRAM_WEBHOOK_SECRET",
    "TELEGRAM_CHANNEL",
    "MATERIALS_SLUG",
    "LLM_ENABLED",
    "ANTHROPIC_API_KEY",
    "RAILWAY_GIT_COMMIT_SHA",
)

# Fake values for the variables required in normal operation (docs/requirements.md, section
# 14); each one is unique so tests can prove that error messages never echo them.
REQUIRED_ENV = {
    "DATABASE_URL": "postgresql://app:sentinel-db-password@localhost:5432/sentinel_db",
    "PUBLIC_BASE_URL": "https://public-sentinel.example.com",
    "EVENT_START": "2026-10-21T19:00",
    "EVENT_END": "2026-10-21T21:00",
    "LESSON_START": "2026-10-28T19:00",
    "LESSON_END": "2026-10-28T21:00",
    "COURSE_URL": "https://course-sentinel.example.com/course",
    "RESEND_API_KEY": "re_sentinel_resend_key",
    "SENDER_EMAIL": "sender-sentinel@example.com",
    "UNSUBSCRIBE_SECRET": "sentinel-unsubscribe-secret-0123456789",
    "ADMIN_TOKEN": "sentinel-admin-token-0123456789abcdef",
    "TURNSTILE_SITE_KEY": "sentinel-turnstile-site-key",
    "TURNSTILE_SECRET_KEY": "sentinel-turnstile-secret-key",
}
# Fake values for optional variables that are secret or identify an account.
OPTIONAL_ENV = {
    "GA4_MEASUREMENT_ID": "G-SENTINEL01",
}
# The optional groups: each works only as a whole (requirements, section 14).
BOT_ENV = {
    "TELEGRAM_BOT_TOKEN": "123456:sentinel-telegram-bot-token",
    "TELEGRAM_BOT_USERNAME": "sentinel_webinar_bot",
    "TELEGRAM_WEBHOOK_SECRET": "sentinel-webhook-secret-0123456789",
    "TELEGRAM_CHANNEL": "@sentinel_channel",
}
LLM_ENV = {"LLM_ENABLED": "true", "ANTHROPIC_API_KEY": "sk-ant-sentinel-anthropic-key"}
SENTINEL_VALUES = {**REQUIRED_ENV, **OPTIONAL_ENV}
# Values that only secrets hold: they never reach a message, a page or a log.
SECRET_VALUES = {
    name: value
    for name, value in {**REQUIRED_ENV, **BOT_ENV, **LLM_ENV}.items()
    if name
    in {
        "DATABASE_URL",
        "RESEND_API_KEY",
        "UNSUBSCRIBE_SECRET",
        "ADMIN_TOKEN",
        "TURNSTILE_SECRET_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_WEBHOOK_SECRET",
        "ANTHROPIC_API_KEY",
    }
}

# Local server from compose.yaml (host port 55433, not the shared default 5432).
DEFAULT_PG_SERVER_URL = "postgresql://app@localhost:55433/app"
TEST_DB_NAME = "app_test"

type SettingsFactory = Callable[..., Settings]
type ParticipantFactory = Callable[..., CreatedParticipant]

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _run_from_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """The app reads docs/ from the working directory, as on Railway (/app)."""
    monkeypatch.chdir(REPO_ROOT)


def is_local(family: int, address: object) -> bool:
    """Whether a socket address stays on this machine: a Unix socket or a loopback address.

    >>> is_local(socket.AF_INET, ("127.0.0.1", 5432)), is_local(socket.AF_INET, ("192.0.2.1", 443))
    (True, False)
    """
    if family == getattr(socket, "AF_UNIX", None):
        return True
    host = address[0] if isinstance(address, tuple) else address
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(str(host)).is_loopback
    except ValueError:
        return False  # a host name: resolving it already leaves the machine


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never reach Turnstile, Telegram, Resend, Claude or Google: nothing leaves the machine.

    Real HTTP transports of httpx, sync and async, refuse to send; Python sockets connect to
    local addresses only. ``httpx.MockTransport`` and ``TestClient`` use their own transports
    and keep working; psycopg reaches the test database through libpq.
    """

    def refuse(_: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        raise RuntimeError(f"tests must not reach the network ({request.url.host})")

    async def refuse_async(_: httpx.AsyncHTTPTransport, request: httpx.Request) -> httpx.Response:
        raise RuntimeError(f"tests must not reach the network ({request.url.host})")

    def stop_remote(sock: socket.socket, address: object) -> None:
        if not is_local(sock.family, address):
            raise RuntimeError(f"tests must not reach the network ({address!r})")

    connect, connect_ex = socket.socket.connect, socket.socket.connect_ex

    def local_connect(sock: socket.socket, address: object) -> None:
        stop_remote(sock, address)
        connect(sock, address)  # type: ignore[arg-type]

    def local_connect_ex(sock: socket.socket, address: object) -> int:
        stop_remote(sock, address)
        return connect_ex(sock, address)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse_async)
    monkeypatch.setattr(socket.socket, "connect", local_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", local_connect_ex)


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


@pytest.fixture
def fresh_engine(test_db_url: str) -> Iterator[Engine]:
    """An engine on the empty test database; the schema is dropped afterwards."""
    with disposable_engine(test_db_url) as engine:
        try:
            yield engine
        finally:
            reset_schema(engine)


@pytest.fixture
def migrated_engine(fresh_engine: Engine) -> Engine:
    """The test database at the latest revision: the whole model of v1 and v2."""
    migrate(fresh_engine, "head")
    return fresh_engine


@pytest.fixture
def participant_factory(migrated_engine: Engine) -> ParticipantFactory:
    """``participant_factory(email=None, *, origin=…, telegram=…, emails=…, link_tokens=…, …)``.

    See ``tests.factories.add_participant``.
    """
    return functools.partial(add_participant, migrated_engine)
