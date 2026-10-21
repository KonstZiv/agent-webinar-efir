"""``POST /telegram/webhook`` (docs/requirements.md, section 7, «Вебхук»).

The secret header is compared in constant time; a wrong one is 403 before the body is read
and before any service of the bot is built. Only private chats count; every other update gets
200, so Telegram does not send it again. An outage of the database or a 429 of Telegram on a
message is 503: Telegram delivers the update again later.
"""

import asyncio
import logging

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.types import Message, Scope

from app.adapters.bot import telegram
from app.adapters.bot.workers import BOT_AT_ONCE, BotWorkers
from app.core.bot.ports import MessengerRateLimited
from app.core.ports import MessengerUnavailable
from app.main import create_app
from app.services import CLOCK, LINK_TOKENS, PARTICIPANTS, override
from app.slices import bot as bot_slice
from tests.bot.conftest import BotSiteFactory, ClientFactory
from tests.bot.helpers import (
    BOT_SITE_ENV,
    NO_BOT,
    OTHER,
    SECRET,
    SECRET_HEADER,
    TOO_DEEP,
    USER,
    WEBHOOK,
    WELCOME,
    BotSite,
    Conflicting,
    Failing,
    Telegram,
    Unavailable,
    app_log,
    expected,
    message_update,
    recheck_update,
    start_update,
)
from tests.conftest import ParticipantFactory, SettingsFactory
from tests.fakes import FakeDatabaseProbe, FixedClock, fake_overrides


def test_an_update_with_the_secret_is_handled(bot_site: BotSite) -> None:
    response = bot_site.start(USER)

    assert response.status_code == 200
    assert bot_site.said() == expected(WELCOME)
    assert bot_site.sent[0].chat_id == USER.user_id


@pytest.mark.parametrize(
    "secret",
    [None, "", SECRET.upper(), SECRET + "x", SECRET[:-1], "wrong-secret-0123456789abcdefghijk"],
    ids=["missing", "empty", "upper", "longer", "shorter", "other"],
)
def test_a_wrong_secret_is_403_and_nothing_happens(
    bot_site: BotSite, participant_factory: ParticipantFactory, secret: str | None
) -> None:
    created = participant_factory(link_tokens=("screen",))

    response = bot_site.post(start_update(USER, created.link_tokens[0]), secret=secret)

    assert response.status_code == 403
    assert bot_site.sent == []
    assert bot_site.linked() == {}
    assert bot_site.link_token(created.link_tokens[0]).used_at is None


def webhook_scope(secret: str | None) -> Scope:
    """``POST /telegram/webhook`` as a server hands it to the application, without its body.

    ``spec_version`` 2.4: the server reports a disconnect on ``send``, so Starlette never calls
    ``receive`` on its own to listen for one; every call of ``receive`` reads the body.
    """
    headers = [(b"host", b"testserver"), (b"content-type", b"application/json")]
    if secret is not None:
        headers.append((SECRET_HEADER.lower().encode(), secret.encode()))
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": WEBHOOK,
        "raw_path": WEBHOOK.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 443),
    }


@pytest.mark.parametrize("secret", [None, "wrong"], ids=["missing", "wrong"])
def test_the_body_is_not_read_without_the_secret(
    make_settings: SettingsFactory, secret: str | None
) -> None:
    """The application answers 403 without asking the server for the body even once."""
    app = create_app(
        make_settings(**BOT_SITE_ENV), db_probe=FakeDatabaseProbe(), overrides=fake_overrides()
    )
    reads: list[Message] = []
    answer: list[Message] = []

    async def receive() -> Message:
        message: Message = {"type": "http.request", "body": b"not json", "more_body": False}
        reads.append(message)
        return message

    async def send(message: Message) -> None:
        answer.append(message)

    asyncio.run(app(webhook_scope(secret), receive, send))

    assert answer[0]["type"] == "http.response.start"
    assert answer[0]["status"] == 403
    assert reads == []


@pytest.mark.parametrize("secret", [None, "wrong"], ids=["missing", "wrong"])
def test_without_the_secret_no_service_of_the_bot_is_built(
    make_settings: SettingsFactory, monkeypatch: pytest.MonkeyPatch, secret: str | None
) -> None:
    """A stranger's request builds neither the Telegram client nor the bot's threads."""
    built: list[str] = []

    def make_http_client() -> httpx.Client:
        built.append("telegram client")
        return httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500)))

    class Workers(BotWorkers):
        def __init__(self, size: int = BOT_AT_ONCE) -> None:
            built.append("bot threads")
            super().__init__(size)

    monkeypatch.setattr(telegram, "make_http_client", make_http_client)
    monkeypatch.setattr(bot_slice, "BotWorkers", Workers)
    # An http site registers no webhook at start-up, so nothing is built before the requests.
    settings = make_settings(**BOT_SITE_ENV, PUBLIC_BASE_URL="http://localhost:8000")
    app = create_app(
        settings, db_probe=FakeDatabaseProbe(), overrides=[override(CLOCK, FixedClock())]
    )
    headers = {} if secret is None else {SECRET_HEADER: secret}

    with TestClient(app, base_url="https://testserver") as client:
        assert client.post(WEBHOOK, json=start_update(USER), headers=headers).status_code == 403
        assert built == []
        # With the secret they are built: the check above would see them.
        ignored = message_update(USER, "hello")
        assert (
            client.post(WEBHOOK, json=ignored, headers={SECRET_HEADER: SECRET}).status_code == 200
        )
        assert sorted(built) == ["bot threads", "telegram client"]


def test_without_the_bot_settings_the_route_is_404(client_factory: ClientFactory) -> None:
    client = client_factory(**NO_BOT)

    response = client.post(
        "/telegram/webhook",
        json=start_update(USER),
        headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
    )

    assert response.status_code == 404
    assert client.get("/healthz").status_code == 200


@pytest.mark.parametrize("chat_type", ["group", "supergroup"])
def test_chats_other_than_private_get_200_and_nothing_else(
    bot_site: BotSite, participant_factory: ParticipantFactory, chat_type: str
) -> None:
    created = participant_factory(link_tokens=("email",))
    text = f"/start {created.link_tokens[0]}"

    response = bot_site.post(message_update(USER, text, chat_type=chat_type, chat_id=-100123))

    assert response.status_code == 200
    assert bot_site.sent == []
    assert bot_site.linked() == {}
    assert bot_site.link_token(created.link_tokens[0]).used_at is None


def test_the_button_outside_a_private_chat_is_ignored(
    bot_site: BotSite, participant_factory: ParticipantFactory
) -> None:
    participant_factory(telegram=USER)

    response = bot_site.post(recheck_update(USER, chat_type="group"))

    assert response.status_code == 200
    assert bot_site.sent == []
    assert bot_site.messenger.answered == []


@pytest.mark.parametrize(
    "update",
    [
        message_update(USER, "/start", kind="edited_message"),
        message_update(USER, "/start", kind="channel_post", chat_type="channel"),
        message_update(USER, "hello"),
        message_update(USER, "/help"),
        {"update_id": 5, "my_chat_member": {}},
        b"not json",
        b"[]",
        b"[" * TOO_DEEP + b"]" * TOO_DEEP,
    ],
    ids=[
        "edited",
        "channel-post",
        "text",
        "other-command",
        "my-chat-member",
        "not-json",
        "list",
        "nested-too-deep",
    ],
)
def test_other_updates_get_200_and_nothing_else(bot_site: BotSite, update: object) -> None:
    response = bot_site.post(update)

    assert response.status_code == 200
    assert bot_site.sent == []


# --- failures ------------------------------------------------------------------------------


def test_an_outage_of_the_database_is_503(
    bot_site_factory: BotSiteFactory, caplog: pytest.LogCaptureFixture
) -> None:
    """Telegram delivers the update again once the database answers."""
    site = bot_site_factory(
        overrides=[override(PARTICIPANTS, Unavailable()), override(LINK_TOKENS, Unavailable())]
    )

    assert site.start(USER, "Tok-en_1").status_code == 503
    assert site.start(USER).status_code == 503
    assert site.recheck(USER).status_code == 503
    assert site.sent == []
    assert "StorageUnavailable" in app_log(caplog)


@pytest.mark.parametrize(
    ("store", "error"), [(Conflicting, "StorageConflict"), (Failing, "StorageError")]
)
def test_other_storage_failures_are_200_and_an_error_in_the_log(
    bot_site_factory: BotSiteFactory, caplog: pytest.LogCaptureFixture, store: type, error: str
) -> None:
    """A retry would fail the same way: Telegram is told the update is taken."""
    site = bot_site_factory(overrides=[override(PARTICIPANTS, store())])

    response = site.start(USER)

    assert response.status_code == 200
    [logged] = [record for record in caplog.records if error in record.getMessage()]
    assert logged.levelno == logging.ERROR


def test_429_on_a_message_is_503(
    bot_site_factory: BotSiteFactory, caplog: pytest.LogCaptureFixture
) -> None:
    site = bot_site_factory(messenger=Telegram(failures={"send_message": [MessengerRateLimited()]}))

    assert site.start(USER).status_code == 503
    assert "MessengerRateLimited" in app_log(caplog)


def test_other_failures_of_a_message_are_200(
    bot_site_factory: BotSiteFactory, caplog: pytest.LogCaptureFixture
) -> None:
    site = bot_site_factory(messenger=Telegram(failures={"send_message": [MessengerUnavailable()]}))

    assert site.start(USER).status_code == 200
    assert site.sent == []
    assert "Telegram message not sent" in app_log(caplog)


def test_the_log_has_the_kind_of_update_and_its_result(
    bot_site: BotSite, participant_factory: ParticipantFactory, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    created = participant_factory(link_tokens=("screen",))

    bot_site.start(USER, created.link_tokens[0])
    bot_site.start(OTHER)
    bot_site.recheck(USER)
    bot_site.post(message_update(USER, "hello"))

    logged = app_log(caplog)
    assert "Telegram update start_token: linked, not_subscribed" in logged
    assert "Telegram update start: none, welcome" in logged
    assert "Telegram update recheck: none, still_not_subscribed" in logged
    assert "Telegram update ignored" in logged


def test_the_route_reads_no_database_without_a_command(bot_site_factory: BotSiteFactory) -> None:
    """Ignored updates never reach the stores: a broken store does not matter for them."""
    site = bot_site_factory(overrides=[override(PARTICIPANTS, Unavailable())])

    assert site.post(message_update(USER, "hello")).status_code == 200
