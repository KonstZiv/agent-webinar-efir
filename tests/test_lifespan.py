"""Resources the application opens are closed on shutdown, all of them, in order."""

from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main
from app.main import create_app, lifespan
from tests.conftest import SettingsFactory


def test_lifespan_calls_every_closer_on_shutdown() -> None:
    closed: list[str] = []
    app = FastAPI(
        lifespan=lifespan((), (), [lambda: closed.append("a"), lambda: closed.append("b")])
    )

    with TestClient(app):
        assert closed == []

    assert closed == ["a", "b"]


def test_lifespan_reads_closers_registered_after_start() -> None:
    """An engine created on the first request is still disposed."""
    closed: list[str] = []
    late: list[Callable[[], None]] = []
    app = FastAPI(lifespan=lifespan((), (), late))

    with TestClient(app):
        late.append(lambda: closed.append("late"))

    assert closed == ["late"]


class SpyEngine:
    """Stands in for the SQLAlchemy engine: records ``dispose``; queries are not expected."""

    def __init__(self) -> None:
        self.disposed = 0

    def dispose(self) -> None:
        self.disposed += 1


def test_engine_is_registered_and_disposed(
    make_settings: SettingsFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = SpyEngine()
    monkeypatch.setattr(main, "make_engine", lambda url: engine)

    with TestClient(create_app(make_settings())):
        assert engine.disposed == 0

    assert engine.disposed == 1


class TelegramDown(Exception):
    """Stands in for ``MessengerUnavailable`` of a webhook registered on start-up."""


def test_a_failing_start_up_action_is_logged_and_the_application_starts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A slice's start-up action is never critical: the site works without it."""
    ran: list[str] = []

    def register_webhook() -> None:
        raise TelegramDown("https://api.telegram.org/bot123456:sentinel-telegram-bot-token")

    app = FastAPI(lifespan=lifespan([register_webhook, lambda: ran.append("next")], ()))

    @app.get("/up")
    def up() -> str:
        return "up"

    with TestClient(app) as client:
        assert client.get("/up").json() == "up"

    assert ran == ["next"]
    assert "register_webhook" in caplog.text
    assert "TelegramDown" in caplog.text
    assert "sentinel-telegram-bot-token" not in caplog.text


class StartAborted(BaseException):
    """The server stops while the application is starting (a cancellation, an interrupt)."""


def test_closers_run_when_the_start_is_aborted() -> None:
    closed: list[str] = []

    def abort() -> None:
        raise StartAborted

    app = FastAPI(lifespan=lifespan([abort], (), [lambda: closed.append("engine")]))

    with pytest.raises(StartAborted), TestClient(app):
        pass

    assert closed == ["engine"]


def test_a_failing_shut_down_action_is_logged_and_the_rest_still_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Shut-down actions are isolated as the start-up ones: the rest and the closers run."""
    ran: list[str] = []

    def delete_webhook() -> None:
        raise TelegramDown("https://api.telegram.org/bot123456:sentinel-telegram-bot-token")

    # The last registered runs first: the failing action comes before the other one.
    app = FastAPI(
        lifespan=lifespan(
            (), [lambda: ran.append("earlier"), delete_webhook], [lambda: ran.append("engine")]
        )
    )

    with TestClient(app):
        pass

    assert ran == ["earlier", "engine"]
    assert "delete_webhook" in caplog.text
    assert "TelegramDown" in caplog.text
    assert "sentinel-telegram-bot-token" not in caplog.text


class ShutDownAborted(BaseException):
    """The server is cancelled while the application is stopping."""


def test_closers_run_when_the_shut_down_is_aborted() -> None:
    closed: list[str] = []

    def abort() -> None:
        raise ShutDownAborted

    app = FastAPI(lifespan=lifespan((), [abort], [lambda: closed.append("engine")]))

    with pytest.raises(ShutDownAborted), TestClient(app):
        pass

    assert closed == ["engine"]
