"""The slice at start-up: the webhook is registered only from an ``https://`` site.

A local run with the keys of staging must not take the webhook of staging (docs/requirements.md,
section 7). The registration is not critical and runs on a thread of its own: the site starts
without waiting for Telegram, and a temporary failure is tried again after a pause (a fake here:
no test waits for it).
"""

import json
import logging
import time
from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.bot import telegram
from app.adapters.bot.keys import PAUSE
from app.adapters.bot.telegram import TelegramMessenger
from app.adapters.bot.webhook import StoppablePause
from app.adapters.bot.workers import BOT_AT_ONCE
from app.core.bot.webhook import PAUSES
from app.core.ports import MessengerUnavailable
from app.main import create_app
from app.services import CLOCK, MESSENGER, override
from tests.bot.conftest import ClientFactory
from tests.bot.helpers import (
    BOT_SITE_ENV,
    NO_BOT,
    SECRET,
    SITE_URL,
    BlockedTelegram,
    FakePause,
    Telegram,
    app_log,
    wait_until,
)
from tests.conftest import SettingsFactory
from tests.fakes import FakeDatabaseProbe, FakeMessenger, FixedClock, fake_overrides

ALLOWED_UPDATES = ("message", "callback_query")
REGISTERED = "Telegram webhook registered"
NOT_REGISTERED = "Telegram webhook not registered"


def answering(
    *answers: httpx.Response,
) -> tuple[list[httpx.Request], Callable[[], httpx.Client]]:
    """Requests to Telegram, and a client over ``httpx.MockTransport`` that answers ``answers``
    in turn (the last one again and again)."""
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return answers[min(len(requests), len(answers)) - 1]

    return requests, lambda: httpx.Client(transport=httpx.MockTransport(answer))


def ok() -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": True})


def test_the_webhook_is_registered_from_an_https_site(client_factory: ClientFactory) -> None:
    messenger = FakeMessenger()

    client_factory(messenger=messenger)

    wait_until(lambda: messenger.webhooks)
    assert messenger.webhooks == [(f"{SITE_URL}/telegram/webhook", SECRET, ALLOWED_UPDATES)]


def test_telegram_sends_no_more_updates_at_once_than_the_bot_has_threads(
    make_settings: SettingsFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``max_connections`` of the webhook is the size of the bot's pool (test_workers.py): the
    updates the threads cannot take yet wait in Telegram, not in the process, where a slow
    Telegram would hold them past Telegram's patience and get them sent again."""
    requests, client = answering(ok())
    monkeypatch.setattr(telegram, "make_http_client", client)
    app = create_app(
        make_settings(**BOT_SITE_ENV),
        db_probe=FakeDatabaseProbe(),
        overrides=[override(CLOCK, FixedClock())],
    )

    with TestClient(app):
        wait_until(lambda: requests)

    [request] = requests
    assert request.url.path.endswith("/setWebhook")
    assert json.loads(request.content)["max_connections"] == BOT_AT_ONCE


@pytest.mark.parametrize("base", ["http://localhost:8000", "http://127.0.0.1"])
def test_the_webhook_is_not_registered_from_http(
    client_factory: ClientFactory, caplog: pytest.LogCaptureFixture, base: str
) -> None:
    caplog.set_level(logging.INFO)
    messenger = FakeMessenger()

    client_factory(messenger=messenger, PUBLIC_BASE_URL=base)

    assert messenger.webhooks == []
    assert "Telegram webhook not registered: PUBLIC_BASE_URL is not https" in app_log(caplog)


def test_without_the_bot_settings_nothing_is_registered(client_factory: ClientFactory) -> None:
    messenger = FakeMessenger()

    client = client_factory(messenger=messenger, **NO_BOT)

    assert messenger.webhooks == []
    assert client.get("/healthz").status_code == 200


def test_a_failed_registration_does_not_stop_the_site(
    client_factory: ClientFactory, caplog: pytest.LogCaptureFixture
) -> None:
    messenger = Telegram(failures={"set_webhook": [MessengerUnavailable()]})

    client = client_factory(messenger=messenger)

    assert client.get("/healthz").status_code == 200
    wait_until(lambda: NOT_REGISTERED in app_log(caplog))
    assert "Telegram webhook not registered: MessengerUnavailable (not retried)" in app_log(caplog)
    assert "Start-up action" not in caplog.text
    assert SECRET not in caplog.text


def test_the_start_does_not_wait_for_telegram(client_factory: ClientFactory) -> None:
    """Railway takes the service as ready by ``/healthz``: a slow Telegram must not hold it."""
    messenger = BlockedTelegram()

    client = client_factory(messenger=messenger)
    try:
        assert messenger.calling.wait(timeout=5)
        assert client.get("/healthz").status_code == 200
        assert messenger.webhooks == []
    finally:
        messenger.release()

    wait_until(lambda: messenger.webhooks)


@pytest.mark.parametrize(
    ("first", "requests_made", "logged"),
    [
        (httpx.Response(502, text="Bad Gateway"), 2, REGISTERED),
        (
            httpx.Response(
                401, json={"ok": False, "error_code": 401, "description": "Unauthorized"}
            ),
            1,
            "Telegram webhook not registered: MessengerUnavailable (not retried)",
        ),
    ],
    ids=["502-tried-again", "401-not-retried"],
)
def test_the_application_tries_again_only_a_temporary_failure(
    make_settings: SettingsFactory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    first: httpx.Response,
    requests_made: int,
    logged: str,
) -> None:
    """The real adapter on ``httpx.MockTransport``; the pause is a fake."""
    caplog.set_level(logging.INFO, logger="app")
    requests, client = answering(first, ok())
    monkeypatch.setattr(telegram, "make_http_client", client)
    pause = FakePause()
    app = create_app(
        make_settings(**BOT_SITE_ENV),
        db_probe=FakeDatabaseProbe(),
        overrides=[override(CLOCK, FixedClock()), override(PAUSE, pause)],
    )

    with TestClient(app):
        wait_until(lambda: logged in app_log(caplog))

    assert len(requests) == requests_made
    assert pause.waited == [PAUSES[0]] * (requests_made - 1)


def test_the_application_stopping_stops_the_pause(make_settings: SettingsFactory) -> None:
    """A registration waiting for its next attempt does not outlive the application."""
    messenger, pause = FakeMessenger(), FakePause()
    app = create_app(
        make_settings(**BOT_SITE_ENV),
        db_probe=FakeDatabaseProbe(),
        overrides=[*fake_overrides(messenger=messenger), override(PAUSE, pause)],
    )

    with TestClient(app):
        wait_until(lambda: messenger.webhooks)
        assert not pause.stopped

    assert pause.stopped


def test_a_stopped_pause_ends_at_once() -> None:
    pause = StoppablePause()
    assert pause.wait(0) is True

    pause.stop()
    started = time.monotonic()

    assert pause.wait(3600) is False
    assert time.monotonic() - started < 1


def test_without_the_materials_page_the_log_says_so(
    client_factory: ClientFactory, caplog: pytest.LogCaptureFixture
) -> None:
    client_factory(MATERIALS_SLUG=None)

    [logged] = [
        record
        for record in caplog.records
        if record.getMessage()
        == "MATERIALS_SLUG is not set: the bot cannot give the materials link"
    ]
    assert logged.levelno == logging.ERROR


def test_with_the_materials_page_the_log_is_quiet(
    client_factory: ClientFactory, caplog: pytest.LogCaptureFixture
) -> None:
    client_factory()

    assert "MATERIALS_SLUG" not in app_log(caplog)


def test_the_settings_choose_the_telegram_adapter(make_settings: SettingsFactory) -> None:
    """Built on first use, not when the application is created: no client, no network."""
    settings = make_settings(**BOT_SITE_ENV, PUBLIC_BASE_URL="http://localhost:8000")
    app = create_app(
        settings, db_probe=FakeDatabaseProbe(), overrides=[override(CLOCK, FixedClock())]
    )

    with TestClient(app):
        messenger = app.state.container.services.get(MESSENGER)

    assert isinstance(messenger, TelegramMessenger)


def test_without_the_bot_settings_no_messenger_is_provided(make_settings: SettingsFactory) -> None:
    app = create_app(make_settings(), db_probe=FakeDatabaseProbe())

    assert app.state.container.services.find(MESSENGER) is None
