"""Resend HTTP API adapter against a mocked transport (requirements, section 6; no network).

Every attempt carries the same ``Idempotency-Key``. A 429 ``rate_limit_exceeded``, a 5xx answer
or a network failure is retried within the time budget; ``daily_quota_exceeded`` fails at once.
An address that is not on ``REGISTRATION_ALLOWLIST`` gets no request at all: the second barrier
of the staging site. Ported from v1 (agent-webinar-v1, tests/adapters/test_resend.py).
"""

import asyncio
import dataclasses
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.adapters.registration import resend
from app.adapters.registration.resend import (
    API_URL,
    ATTEMPT_TIMEOUT_SECONDS,
    MAX_ATTEMPTS,
    MAX_PAUSE_SECONDS,
    SEND_BUDGET_SECONDS,
    ResendEmailSender,
)
from app.core.entities import Delivered, NotDelivered, OutgoingEmail
from app.main import create_app
from app.services import EMAIL_SENDER
from tests.conftest import REQUIRED_ENV, SettingsFactory
from tests.fakes import FakeDatabaseProbe

API_KEY = "re_sentinel_api_key_value"
KEY = uuid.UUID("11111111-2222-3333-4444-555555555555")
ROUNDING = 1e-9  # the fake clock adds floats
MESSAGE = OutgoingEmail(
    sender="Костянтин Зівенко <sender@example.com>",
    to="visitor@example.com",
    subject="Тема",
    html="<p>HTML</p>",
    text="Текст",
    headers={
        "List-Unsubscribe": "<https://public.example.com/unsubscribe/token>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    },
)

type Handler = Callable[[httpx.Request], httpx.Response]


def ok(resend_id: str = "49a3999c-0ce1-4ea6-ab68-afcd6dc2e794") -> httpx.Response:
    return httpx.Response(200, json={"id": resend_id})


def error(status: int, name: str, headers: dict[str, str] | None = None) -> httpx.Response:
    body = {"statusCode": status, "name": name, "message": "Mail to visitor@example.com failed"}
    return httpx.Response(status, json=body, headers=headers)


class Slow:
    """An answer that takes ``seconds``; past the request timeout it becomes a read timeout."""

    def __init__(self, seconds: float, answer: httpx.Response | Exception) -> None:
        self.seconds = seconds
        self.answer = answer


class Script:
    """Answers requests in order on a fake clock; remembers requests, timeouts and pauses."""

    def __init__(self, *answers: httpx.Response | Exception | Slow) -> None:
        self.answers = list(answers)
        self.requests: list[httpx.Request] = []
        self.starts: list[float] = []
        self.timeouts: list[float] = []
        self.pauses: list[float] = []
        self.now = 0.0

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.starts.append(self.now)
        timeout = request.extensions["timeout"]["read"]
        self.timeouts.append(timeout)
        answer = self.answers.pop(0)
        if isinstance(answer, Slow):
            if answer.seconds > timeout:
                self.now += timeout
                raise httpx.ReadTimeout("timed out", request=request)
            self.now += answer.seconds
            answer = answer.answer
        if isinstance(answer, Exception):
            raise answer
        return answer

    def sleep(self, seconds: float) -> None:
        self.pauses.append(seconds)
        self.now += seconds

    def sender(self, allowlist: tuple[str, ...] = ()) -> ResendEmailSender:
        transport = httpx.MockTransport(self.handle)
        return ResendEmailSender(
            SecretStr(API_KEY),
            lambda: httpx.AsyncClient(transport=transport),
            allowlist=allowlist,
            sleep=self.sleep,
            monotonic=lambda: self.now,
        )


def test_request_carries_the_message_key_and_headers() -> None:
    script = Script(ok())

    result = script.sender().send(MESSAGE, KEY)

    assert result == Delivered(provider_id="49a3999c-0ce1-4ea6-ab68-afcd6dc2e794", attempts=1)
    [request] = script.requests
    assert request.method == "POST"
    assert str(request.url) == API_URL == "https://api.resend.com/emails"
    assert request.headers["authorization"] == f"Bearer {API_KEY}"
    assert request.headers["idempotency-key"] == str(KEY)
    assert json.loads(request.content) == {
        "from": MESSAGE.sender,
        "to": [MESSAGE.to],
        "subject": MESSAGE.subject,
        "html": MESSAGE.html,
        "text": MESSAGE.text,
        "headers": dict(MESSAGE.headers),
    }
    assert script.pauses == []


def test_rate_limit_is_retried_after_retry_after() -> None:
    script = Script(error(429, "rate_limit_exceeded", {"Retry-After": "2"}), ok())

    result = script.sender().send(MESSAGE, KEY)

    assert isinstance(result, Delivered)
    assert result.attempts == 2
    assert script.pauses == [2.0]
    assert {r.headers["idempotency-key"] for r in script.requests} == {str(KEY)}


@pytest.mark.parametrize("name", ["daily_quota_exceeded", "monthly_quota_exceeded"])
def test_quota_fails_at_once(name: str) -> None:
    """A spent quota is flagged: no email goes out until it renews (the retry stops)."""
    script = Script(error(429, name, {"Retry-After": "1"}))

    result = script.sender().send(MESSAGE, KEY)

    assert result == NotDelivered(
        error=f"HTTP 429 {name}", attempts=1, rejected=True, out_of_quota=True
    )
    assert len(script.requests) == 1
    assert script.pauses == []


def test_server_errors_are_retried_three_times_in_all() -> None:
    script = Script(*(error(500, "application_error") for _ in range(MAX_ATTEMPTS)))

    result = script.sender().send(MESSAGE, KEY)

    assert result == NotDelivered(
        error="HTTP 500 application_error", attempts=MAX_ATTEMPTS, rejected=False
    )
    assert len(script.requests) == MAX_ATTEMPTS == 3
    assert script.pauses == [1.0, 2.0]


def test_network_failure_is_retried() -> None:
    script = Script(httpx.ConnectTimeout("timed out"), error(503, "service_unavailable"), ok())

    result = script.sender().send(MESSAGE, KEY)

    assert isinstance(result, Delivered)
    assert result.attempts == 3


def test_network_failure_every_time() -> None:
    script = Script(*(httpx.ConnectError("refused") for _ in range(MAX_ATTEMPTS)))

    assert script.sender().send(MESSAGE, KEY) == NotDelivered(
        error="network ConnectError", attempts=3, rejected=False
    )


@pytest.mark.parametrize(
    ("status", "name", "rejected"),
    [
        (422, "validation_error", True),
        (403, "validation_error", True),
        (401, "missing_api_key", True),
        # An earlier request with this key exists and its fate is unknown.
        (409, "concurrent_idempotent_requests", False),
        (409, "invalid_idempotent_request", False),
    ],
)
def test_other_errors_fail_at_once(status: int, name: str, rejected: bool) -> None:
    script = Script(error(status, name))

    assert script.sender().send(MESSAGE, KEY) == NotDelivered(
        error=f"HTTP {status} {name}", attempts=1, rejected=rejected
    )


def test_rate_limit_every_time_is_a_rejection() -> None:
    """Three 429 answers: Resend never took the email, so a later retry may use a new key."""
    script = Script(*(error(429, "rate_limit_exceeded") for _ in range(MAX_ATTEMPTS)))

    assert script.sender().send(MESSAGE, KEY) == NotDelivered(
        error="HTTP 429 rate_limit_exceeded", attempts=3, rejected=True
    )


@pytest.mark.parametrize(
    "first",
    [error(500, "application_error"), httpx.ConnectTimeout("timed out")],
    ids=["5xx", "network"],
)
def test_rejection_after_an_unknown_attempt_is_not_certain(
    first: httpx.Response | Exception,
) -> None:
    """The first attempt may have sent the email: the key must stay."""
    script = Script(first, error(429, "rate_limit_exceeded"), error(422, "validation_error"))

    result = script.sender().send(MESSAGE, KEY)

    assert result == NotDelivered(error="HTTP 422 validation_error", attempts=3, rejected=False)


def test_one_email_takes_at_most_the_budget() -> None:
    """Slow answers and pauses together stay within ~15 s; the last attempt gets what is left."""
    script = Script(
        Slow(60, error(500, "application_error")),
        Slow(60, error(500, "application_error")),
        Slow(60, error(500, "application_error")),
    )

    result = script.sender().send(MESSAGE, KEY)

    assert script.timeouts == [ATTEMPT_TIMEOUT_SECONDS, ATTEMPT_TIMEOUT_SECONDS, 2.0]
    assert script.pauses == [1.0, 2.0]
    assert script.now <= SEND_BUDGET_SECONDS + ROUNDING
    assert SEND_BUDGET_SECONDS == 15.0
    assert result == NotDelivered(error="network ReadTimeout", attempts=3, rejected=False)


class Dripping(httpx.SyncByteStream, httpx.AsyncByteStream):
    """A body that comes in small parts, each well within any read timeout: ``seconds`` in all."""

    def __init__(self, seconds: float, parts: int = 20) -> None:
        self.pause = seconds / parts
        self.parts = parts

    def __iter__(self) -> Iterator[bytes]:
        for _ in range(self.parts):
            time.sleep(self.pause)
            yield b" "
        yield b'{"id": "late"}'

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for _ in range(self.parts):
            await asyncio.sleep(self.pause)
            yield b" "
        yield b'{"id": "late"}'


def test_the_budget_bounds_the_whole_send_even_when_the_answer_drips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """httpx's timeouts bound each read, not a request: a dripping answer would hold the thread.

    Real time on a short budget: the attempt is cut when the budget is spent, its fate unknown.
    """
    budget = 0.5
    monkeypatch.setattr(resend, "SEND_BUDGET_SECONDS", budget)
    monkeypatch.setattr(resend, "ATTEMPT_TIMEOUT_SECONDS", budget)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=Dripping(2.0)))
    sender = ResendEmailSender(SecretStr(API_KEY), lambda: httpx.AsyncClient(transport=transport))

    started = time.monotonic()
    result = sender.send(MESSAGE, KEY)
    elapsed = time.monotonic() - started

    assert elapsed < budget + 0.3
    assert isinstance(result, NotDelivered)
    assert result.error.startswith("network ")
    assert (result.attempts, result.rejected) == (1, False)


def test_no_retry_when_the_pause_would_pass_the_budget() -> None:
    script = Script(
        Slow(60, error(500, "application_error")),
        Slow(4, error(429, "rate_limit_exceeded", {"Retry-After": "5"})),
    )

    result = script.sender().send(MESSAGE, KEY)

    assert len(script.requests) == 2
    assert script.pauses == [1.0]  # 5 + 1 + 4 + 5 s would leave no time for a third attempt
    assert result == NotDelivered(error="HTTP 429 rate_limit_exceeded", attempts=2, rejected=False)


@pytest.mark.parametrize(
    "answers",
    [
        [Slow(60, ok()), Slow(60, ok()), Slow(60, ok())],
        [Slow(4.9, error(503, "x")), Slow(4.9, error(503, "x")), Slow(4.9, ok())],
        [
            error(429, "rate_limit_exceeded", {"Retry-After": "5"}),
            error(429, "rate_limit_exceeded", {"Retry-After": "5"}),
            Slow(60, ok()),
        ],
    ],
    ids=["timeouts", "slow-5xx", "long-pauses"],
)
def test_every_request_timeout_fits_the_time_left(answers: list[httpx.Response | Slow]) -> None:
    script = Script(*answers)

    script.sender().send(MESSAGE, KEY)

    assert len(script.requests) == MAX_ATTEMPTS
    for start, timeout in zip(script.starts, script.timeouts, strict=True):
        assert start + timeout <= SEND_BUDGET_SECONDS + ROUNDING
    assert script.now <= SEND_BUDGET_SECONDS + ROUNDING


def test_long_retry_after_is_capped() -> None:
    script = Script(error(429, "rate_limit_exceeded", {"Retry-After": "999"}), ok())

    script.sender().send(MESSAGE, KEY)

    assert script.pauses == [MAX_PAUSE_SECONDS] == [5.0]


@pytest.mark.parametrize("value", ["soon", "-5", "nan", "Wed, 21 Oct 2026 07:28:00 GMT"])
def test_unusable_retry_after_falls_back(value: str) -> None:
    script = Script(error(429, "rate_limit_exceeded", {"Retry-After": value}), ok())

    script.sender().send(MESSAGE, KEY)

    assert len(script.pauses) == 1
    assert 0 <= script.pauses[0] <= MAX_PAUSE_SECONDS


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(429, content=b"<html>Too Many Requests</html>"),
        httpx.Response(429, json={"name": "Rate limit exceeded\nforged line"}),
        httpx.Response(429, json=["not", "an", "object"]),
    ],
)
def test_unrecognised_error_body_is_neither_retried_nor_stored(answer: httpx.Response) -> None:
    script = Script(answer)

    assert script.sender().send(MESSAGE, KEY) == NotDelivered(
        error="HTTP 429 unknown", attempts=1, rejected=True
    )


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(200, json={"id": "x" * 101}),
        httpx.Response(200, json={"id": "bad id\n"}),
        httpx.Response(200, json={}),
        httpx.Response(200, content=b"not json"),
    ],
)
def test_odd_id_is_not_stored(answer: httpx.Response) -> None:
    """``Delivered.provider_id`` is a string: an empty one means «nothing to store»."""
    script = Script(answer)

    assert script.sender().send(MESSAGE, KEY) == Delivered(provider_id="", attempts=1)


def test_log_has_neither_key_nor_address(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    script = Script(
        error(429, "rate_limit_exceeded"), httpx.ConnectError("refused"), error(429, "x_y")
    )

    script.sender().send(MESSAGE, KEY)

    assert API_KEY not in caplog.text
    assert "visitor@example.com" not in caplog.text
    assert "rate_limit_exceeded" in caplog.text


def test_repr_hides_the_key() -> None:
    assert API_KEY not in repr(Script().sender())


# --- the allowlist of the staging site (requirements, section 5) ---------------------------


def replace_to(message: OutgoingEmail, recipient: str) -> OutgoingEmail:
    return dataclasses.replace(message, to=recipient)


@pytest.mark.parametrize(
    "recipient", ["visitor@example.com", "visitor+rehearsal-1@example.com", "visitor+@example.com"]
)
def test_an_address_on_the_allowlist_is_sent(recipient: str) -> None:
    script = Script(ok())

    result = script.sender(allowlist=("visitor@example.com",)).send(
        replace_to(MESSAGE, recipient), KEY
    )

    assert isinstance(result, Delivered)
    assert len(script.requests) == 1


@pytest.mark.parametrize(
    "recipient", ["stranger@example.com", "visitor@other.example.com", "other+visitor@example.com"]
)
def test_an_address_off_the_allowlist_gets_no_request(
    recipient: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    script = Script()

    result = script.sender(allowlist=("visitor@example.com",)).send(
        replace_to(MESSAGE, recipient), KEY
    )

    assert result == NotDelivered(error="recipient not on the allowlist", attempts=0, rejected=True)
    assert script.requests == []
    assert recipient not in caplog.text


def test_an_empty_allowlist_sends_to_everyone() -> None:
    script = Script(ok())

    assert isinstance(
        script.sender().send(replace_to(MESSAGE, "anyone@other.example.com"), KEY), Delivered
    )


@pytest.fixture
def application_sender(make_settings: SettingsFactory) -> Iterator[ResendEmailSender]:
    settings = make_settings(REGISTRATION_ALLOWLIST="Visitor@Example.com, tester@example.com")
    app = create_app(settings, db_probe=FakeDatabaseProbe())
    with TestClient(app):
        sender = app.state.container.services.get(EMAIL_SENDER)
        assert isinstance(sender, ResendEmailSender)
        yield sender


def test_the_application_refuses_addresses_off_its_allowlist(
    application_sender: ResendEmailSender,
) -> None:
    """The real adapter is wired with the setting; refusing reaches no network."""
    result = application_sender.send(replace_to(MESSAGE, "stranger@example.com"), KEY)

    assert result == NotDelivered(error="recipient not on the allowlist", attempts=0, rejected=True)
    assert REQUIRED_ENV["RESEND_API_KEY"] not in repr(application_sender)
