"""Registering the webhook: a temporary failure of Telegram is tried again, a refusal is not.

A timeout, the network, a 5xx (``MessengerDown``) and a 429 with ``retry_after`` pass: the same
request may work a few seconds later. A wrong token or address does not, and neither does a 429
that does not say how long to wait. The log says the webhook is not registered once, after the
last attempt. The pause is a fake: no test waits.
"""

import logging

import pytest

from app.core.bot.ports import MessengerDown, MessengerRateLimited
from app.core.bot.webhook import ATTEMPTS, PAUSES, RETRY_AFTER_LIMIT, register_webhook
from app.core.ports import MessengerUnavailable
from tests.bot.helpers import BOT_TOKEN, SECRET, FakePause, Telegram, app_log

URL = "https://site.example.com/telegram/webhook"
ALLOWED_UPDATES = ("message", "callback_query")
NOT_REGISTERED = "Telegram webhook not registered"


@pytest.fixture(autouse=True)
def _info(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="app")


def register(telegram: Telegram, pause: FakePause) -> bool:
    return register_webhook(telegram, pause, URL, SECRET, ALLOWED_UPDATES)


def failing(*errors: Exception | None) -> Telegram:
    """Telegram whose ``setWebhook`` raises ``errors`` in turn, then works."""
    return Telegram(failures={"set_webhook": list(errors)})


def errors_logged(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.levelno >= logging.ERROR]


def test_there_are_a_few_attempts() -> None:
    assert len(PAUSES) + 1 == ATTEMPTS
    assert ATTEMPTS >= 3


def test_the_first_attempt_registers(caplog: pytest.LogCaptureFixture) -> None:
    telegram, pause = Telegram(), FakePause()

    assert register(telegram, pause) is True

    assert telegram.webhooks == [(URL, SECRET, ALLOWED_UPDATES)]
    assert pause.waited == []
    assert "Telegram webhook registered" in app_log(caplog)


@pytest.mark.parametrize(
    "error",
    [MessengerDown(), MessengerRateLimited(retry_after=1)],
    ids=["down", "429-retry-after"],
)
def test_a_temporary_failure_is_tried_again(
    caplog: pytest.LogCaptureFixture, error: Exception
) -> None:
    telegram, pause = failing(error, None), FakePause()

    assert register(telegram, pause) is True

    assert telegram.calls == ["set_webhook", "set_webhook"]
    assert telegram.webhooks == [(URL, SECRET, ALLOWED_UPDATES)]
    assert pause.waited == [PAUSES[0]]
    assert NOT_REGISTERED not in app_log(caplog)
    assert errors_logged(caplog) == []


def test_each_attempt_that_fails_is_logged_with_the_next_pause(
    caplog: pytest.LogCaptureFixture,
) -> None:
    register(failing(MessengerDown(), None), FakePause())

    assert (
        f"Telegram webhook attempt 1 of {ATTEMPTS} failed: MessengerDown; next in 2 s"
        in app_log(caplog)
    )


def test_not_registered_is_logged_once_after_the_last_attempt(
    caplog: pytest.LogCaptureFixture,
) -> None:
    telegram, pause = failing(*[MessengerDown()] * ATTEMPTS), FakePause()

    assert register(telegram, pause) is False

    assert telegram.calls == ["set_webhook"] * ATTEMPTS
    assert telegram.webhooks == []
    assert pause.waited == list(PAUSES)
    [logged] = errors_logged(caplog)
    assert logged.getMessage() == (
        f"Telegram webhook not registered after {ATTEMPTS} attempts: MessengerDown"
    )
    assert caplog.records[-1] is logged
    assert app_log(caplog).count(NOT_REGISTERED) == 1


@pytest.mark.parametrize(
    "error",
    [MessengerUnavailable(), MessengerRateLimited()],
    ids=["refused", "429-without-retry-after"],
)
def test_a_refusal_is_not_tried_again(caplog: pytest.LogCaptureFixture, error: Exception) -> None:
    """A wrong token (401, 404) or address (400) fails the same way every time."""
    telegram, pause = failing(error, None), FakePause()

    assert register(telegram, pause) is False

    assert telegram.calls == ["set_webhook"]
    assert pause.waited == []
    [logged] = errors_logged(caplog)
    assert logged.getMessage() == (
        f"Telegram webhook not registered: {type(error).__name__} (not retried)"
    )


@pytest.mark.parametrize(
    ("retry_after", "paused"),
    [(7, 7.0), (1, PAUSES[0]), (RETRY_AFTER_LIMIT, float(RETRY_AFTER_LIMIT))],
    ids=["longer-than-planned", "shorter-than-planned", "at-the-limit"],
)
def test_429_waits_at_least_as_long_as_telegram_asks(retry_after: int, paused: float) -> None:
    telegram, pause = failing(MessengerRateLimited(retry_after=retry_after), None), FakePause()

    assert register(telegram, pause) is True

    assert pause.waited == [paused]


def test_429_asking_too_long_a_wait_ends_the_attempts(caplog: pytest.LogCaptureFixture) -> None:
    too_long = RETRY_AFTER_LIMIT + 1
    telegram, pause = failing(MessengerRateLimited(retry_after=too_long), None), FakePause()

    assert register(telegram, pause) is False

    assert telegram.calls == ["set_webhook"]
    assert pause.waited == []
    [logged] = errors_logged(caplog)
    assert logged.getMessage() == (
        f"Telegram webhook not registered: Telegram asks to wait {too_long} s"
    )


def test_the_application_stopping_ends_the_attempts(caplog: pytest.LogCaptureFixture) -> None:
    telegram, pause = failing(MessengerDown(), None), FakePause(stops_at=1)

    assert register(telegram, pause) is False

    assert telegram.calls == ["set_webhook"]
    assert telegram.webhooks == []
    assert "Telegram webhook not registered: the application stops" in app_log(caplog)
    assert errors_logged(caplog) == []


def test_the_log_has_no_secret_and_no_address(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    telegram = failing(MessengerDown(), MessengerRateLimited(retry_after=3), MessengerUnavailable())

    register(telegram, FakePause())

    assert caplog.records
    for secret in (SECRET, URL, BOT_TOKEN.split(":", 1)[1]):
        assert secret not in caplog.text
