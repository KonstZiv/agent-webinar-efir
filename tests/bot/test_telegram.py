"""The Telegram Bot API adapter on ``httpx.MockTransport``: requests, answers, failures, the log.

The bot token is a part of every API address, so neither the log (httpx's own included) nor an
exception may carry an address. A 429 fails at once: a handler never waits for Telegram. A
temporary failure (``MessengerDown``) is told from a refusal: only the first is worth another try.
"""

import json
import logging
import time
import traceback
from collections.abc import Callable

import httpx
import pytest
from pydantic import SecretStr

from app.adapters.bot.telegram import TIMEOUT, MaskBotToken, TelegramMessenger, make_http_client
from app.core.bot.ports import MessengerDown, MessengerRateLimited
from app.core.entities import Button, ChatMember
from app.core.ports import MessengerUnavailable
from tests.bot.helpers import BOT_TOKEN

type Handler = Callable[[httpx.Request], httpx.Response]

API = f"https://api.telegram.org/bot{BOT_TOKEN}"
TOKEN_SECRET_PART = BOT_TOKEN.split(":", 1)[1]


class Recorder:
    """A transport handler that answers as told and keeps every request."""

    def __init__(self, answer: Handler | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.answer = answer or (lambda _: ok(True))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.answer(request)

    @property
    def bodies(self) -> list[object]:
        return [json.loads(request.content) for request in self.requests]


def ok(result: object) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": result})


def error(status: int, description: str, **parameters: object) -> httpx.Response:
    body: dict[str, object] = {"ok": False, "error_code": status, "description": description}
    if parameters:
        body["parameters"] = parameters
    return httpx.Response(status, json=body)


def messenger(handler: Handler, *, max_connections: int = 8) -> TelegramMessenger:
    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=TIMEOUT)
    return TelegramMessenger(SecretStr(BOT_TOKEN), client, max_connections=max_connections)


# --- requests ------------------------------------------------------------------------------


def test_a_message_with_buttons() -> None:
    recorder = Recorder()
    buttons = [
        [Button("Перейти в канал", url="https://t.me/channel")],
        [Button("Перевірити ще раз", callback_data="recheck")],
    ]

    messenger(recorder).send_message(987654321, "Текст", buttons)

    [request] = recorder.requests
    assert request.method == "POST"
    assert str(request.url) == f"{API}/sendMessage"
    assert recorder.bodies == [
        {
            "chat_id": 987654321,
            "text": "Текст",
            "reply_markup": {
                "inline_keyboard": [
                    [{"text": "Перейти в канал", "url": "https://t.me/channel"}],
                    [{"text": "Перевірити ще раз", "callback_data": "recheck"}],
                ]
            },
        }
    ]


def test_a_message_without_buttons_has_no_keyboard() -> None:
    recorder = Recorder()

    messenger(recorder).send_message(987654321, "Текст")

    assert recorder.bodies == [{"chat_id": 987654321, "text": "Текст"}]


def test_answering_a_button() -> None:
    recorder = Recorder()

    messenger(recorder).answer_callback("callback-1")

    assert str(recorder.requests[0].url) == f"{API}/answerCallbackQuery"
    assert recorder.bodies == [{"callback_query_id": "callback-1"}]


@pytest.mark.parametrize(
    ("result", "member"),
    [
        ({"status": "member", "user": {"id": 1}}, ChatMember("member")),
        ({"status": "restricted", "is_member": True}, ChatMember("restricted", True)),
        ({"status": "restricted", "is_member": False}, ChatMember("restricted", False)),
        ({"status": "left"}, ChatMember("left")),
    ],
)
def test_a_channel_member(result: dict[str, object], member: ChatMember) -> None:
    recorder = Recorder(lambda _: ok(result))

    assert messenger(recorder).channel_member("@channel", 987654321) == member
    assert str(recorder.requests[0].url) == f"{API}/getChatMember"
    assert recorder.bodies == [{"chat_id": "@channel", "user_id": 987654321}]


def test_setting_the_webhook() -> None:
    """``max_connections``: the updates the process cannot take yet wait in Telegram."""
    recorder = Recorder()

    messenger(recorder, max_connections=3).set_webhook(
        "https://site.example.com/telegram/webhook", "secret-value", ("message", "callback_query")
    )

    assert str(recorder.requests[0].url) == f"{API}/setWebhook"
    assert recorder.bodies == [
        {
            "url": "https://site.example.com/telegram/webhook",
            "secret_token": "secret-value",
            "allowed_updates": ["message", "callback_query"],
            "max_connections": 3,
        }
    ]


# --- failures ------------------------------------------------------------------------------


def network_down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def read_timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timed out", request=request)


@pytest.mark.parametrize(
    "answer",
    [
        network_down,
        read_timeout,
        lambda _: httpx.Response(502, text="Bad Gateway"),
        lambda _: error(400, "Bad Request: chat not found"),
        lambda _: error(403, "Forbidden: bot was blocked by the user"),
        lambda _: httpx.Response(200, text="not json"),
        lambda _: httpx.Response(200, json=["not", "an", "object"]),
        lambda _: httpx.Response(200, json={"ok": False}),
    ],
    ids=["network", "timeout", "502", "400", "403", "not-json", "not-an-object", "not-ok"],
)
def test_every_failure_is_messenger_unavailable(answer: Handler) -> None:
    telegram = messenger(Recorder(answer))

    with pytest.raises(MessengerUnavailable) as raised:
        telegram.send_message(987654321, "Текст")

    assert not isinstance(raised.value, MessengerRateLimited)


def server_disconnected(request: httpx.Request) -> httpx.Response:
    raise httpx.RemoteProtocolError("Server disconnected without sending a response.")


def connect_timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectTimeout("timed out", request=request)


def set_webhook(telegram: TelegramMessenger) -> None:
    telegram.set_webhook("https://site.example.com/telegram/webhook", "secret-value", ("message",))


@pytest.mark.parametrize(
    "answer",
    [
        network_down,
        read_timeout,
        connect_timeout,
        server_disconnected,
        lambda _: error(500, "Internal Server Error"),
        lambda _: httpx.Response(502, text="Bad Gateway"),
        lambda _: httpx.Response(503, text="Service Unavailable"),
    ],
    ids=["network", "read-timeout", "connect-timeout", "disconnected", "500", "502", "503"],
)
def test_a_temporary_failure_is_messenger_down(answer: Handler) -> None:
    with pytest.raises(MessengerDown):
        set_webhook(messenger(Recorder(answer)))


@pytest.mark.parametrize(
    "answer",
    [
        lambda _: error(400, "Bad Request: bad webhook: Failed to resolve host"),
        lambda _: error(401, "Unauthorized"),
        lambda _: error(403, "Forbidden: bot was blocked by the user"),
        lambda _: error(404, "Not Found"),
        lambda _: httpx.Response(200, text="not json"),
        lambda _: httpx.Response(200, json=["not", "an", "object"]),
        lambda _: httpx.Response(200, json={"ok": False}),
    ],
    ids=["400-address", "401-token", "403", "404-token", "not-json", "not-an-object", "not-ok"],
)
def test_a_refusal_is_not_messenger_down(answer: Handler) -> None:
    with pytest.raises(MessengerUnavailable) as raised:
        set_webhook(messenger(Recorder(answer)))

    assert not isinstance(raised.value, MessengerDown | MessengerRateLimited)


def test_a_token_httpx_cannot_put_into_an_address_is_not_messenger_down() -> None:
    client = httpx.Client(transport=httpx.MockTransport(Recorder()), timeout=TIMEOUT)
    telegram = TelegramMessenger(SecretStr("123456:broken\ntoken"), client, max_connections=8)

    with pytest.raises(MessengerUnavailable) as raised:
        set_webhook(telegram)

    assert not isinstance(raised.value, MessengerDown)


def test_429_carries_retry_after() -> None:
    recorder = Recorder(lambda _: error(429, "Too Many Requests: retry after 30", retry_after=30))

    with pytest.raises(MessengerRateLimited) as raised:
        set_webhook(messenger(recorder))

    assert raised.value.retry_after == 30


@pytest.mark.parametrize(
    "answer",
    [
        lambda _: error(429, "Too Many Requests"),
        lambda _: error(429, "Too Many Requests", retry_after="30"),
        lambda _: httpx.Response(429, text="Too Many Requests"),
    ],
    ids=["no-parameters", "not-a-number", "not-json"],
)
def test_429_without_retry_after(caplog: pytest.LogCaptureFixture, answer: Handler) -> None:
    with pytest.raises(MessengerRateLimited) as raised:
        set_webhook(messenger(Recorder(answer)))

    assert raised.value.retry_after is None
    assert "retry after ? s" in caplog.text


@pytest.mark.parametrize(
    "result",
    [{"user": {"id": 1}}, {"status": 42}, "member", None],
    ids=["no-status", "status-not-text", "not-an-object", "null"],
)
def test_a_channel_member_of_an_unexpected_shape_is_a_failure(result: object) -> None:
    with pytest.raises(MessengerUnavailable):
        messenger(Recorder(lambda _: ok(result))).channel_member("@channel", 987654321)


def test_429_fails_at_once(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The handler does not wait out ``retry_after``: Telegram delivers the update again."""
    caplog.set_level(logging.INFO)
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    recorder = Recorder(lambda _: error(429, "Too Many Requests: retry after 30", retry_after=30))

    started = time.monotonic()
    with pytest.raises(MessengerRateLimited):
        messenger(recorder).send_message(987654321, "Текст")

    assert time.monotonic() - started < 1
    assert slept == []
    assert len(recorder.requests) == 1
    assert "retry after 30 s" in caplog.text


def test_the_log_names_the_method_and_the_answer(caplog: pytest.LogCaptureFixture) -> None:
    telegram = messenger(Recorder(lambda _: error(400, "Bad Request: member list is inaccessible")))

    with pytest.raises(MessengerUnavailable):
        telegram.channel_member("@channel", 987654321)

    assert "getChatMember" in caplog.text
    assert "HTTP 400" in caplog.text
    assert "Bad Request: member list is inaccessible" in caplog.text


def test_a_description_with_numbers_stays_out_of_the_log(caplog: pytest.LogCaptureFixture) -> None:
    telegram = messenger(Recorder(lambda _: error(400, "Bad Request: chat 987654321 not found")))

    with pytest.raises(MessengerUnavailable):
        telegram.send_message(987654321, "Текст")

    assert "987654321" not in caplog.text


def test_httpx_logs_the_address_with_the_token_masked(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)  # httpx logs every request with its address at INFO

    messenger(Recorder()).send_message(987654321, "Текст")

    [logged] = [record.getMessage() for record in caplog.records if record.name == "httpx"]
    assert "https://api.telegram.org/bot***/sendMessage" in logged
    assert TOKEN_SECRET_PART not in logged


@pytest.mark.parametrize(
    "answer",
    [network_down, read_timeout, lambda _: error(500, "Internal Server Error")],
    ids=["network", "timeout", "500"],
)
def test_the_bot_token_stays_out_of_logs_and_errors(
    caplog: pytest.LogCaptureFixture, answer: Handler
) -> None:
    caplog.set_level(logging.DEBUG)
    telegram = messenger(Recorder(answer))

    with pytest.raises(MessengerUnavailable) as raised:
        telegram.send_message(987654321, "Текст")

    shown = "".join(traceback.format_exception(raised.value)) + repr(raised.value)
    assert TOKEN_SECRET_PART not in shown
    assert caplog.records
    assert TOKEN_SECRET_PART not in caplog.text


def test_a_token_httpx_cannot_put_into_an_address_is_a_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = httpx.Client(transport=httpx.MockTransport(Recorder()), timeout=TIMEOUT)
    telegram = TelegramMessenger(SecretStr("123456:broken\ntoken"), client, max_connections=8)

    with pytest.raises(MessengerUnavailable) as raised:
        telegram.send_message(987654321, "Текст")

    assert "broken" not in "".join(traceback.format_exception(raised.value)) + caplog.text


def test_the_adapter_does_not_show_its_token() -> None:
    assert TOKEN_SECRET_PART not in repr(messenger(Recorder()))


def test_the_client_has_timeouts() -> None:
    client = make_http_client()
    try:
        assert client.timeout == httpx.Timeout(5.0, connect=3.0)
    finally:
        client.close()


def test_the_token_mask_is_installed_once() -> None:
    messenger(Recorder())
    messenger(Recorder())

    masks = [item for item in logging.getLogger("httpx").filters if isinstance(item, MaskBotToken)]
    assert len(masks) == 1
