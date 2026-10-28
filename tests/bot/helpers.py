"""Helpers of the bot tests: the application on the test database, Telegram updates, the texts.

``BotSite`` is the application of ``create_app`` with the bot settings on the migrated test
database: the stores of participants and link tokens are real, Telegram and the clock are fakes
(tests/fakes.py). The expected texts come from docs/copy.md, section 8, read here on their own
(``bot_copy``), never from the application.
"""

import itertools
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.adapters.db.models import LinkToken, Participant
from app.core.bot.replies import RECHECK
from app.core.entities import Button, ChatMember, TelegramAccount
from app.core.ports import StorageConflict, StorageError, StorageUnavailable
from app.settings import Settings
from tests import copy_oracle as copy
from tests.conftest import BOT_ENV, REQUIRED_ENV
from tests.fakes import FakeMessenger, FixedClock, SentMessage

SECRET = BOT_ENV["TELEGRAM_WEBHOOK_SECRET"]
BOT_TOKEN = BOT_ENV["TELEGRAM_BOT_TOKEN"]
CHANNEL = BOT_ENV["TELEGRAM_CHANNEL"]
CHANNEL_URL = "https://t.me/" + CHANNEL.removeprefix("@")
SITE_URL = REQUIRED_ENV["PUBLIC_BASE_URL"]
SLUG = "Sentinel_Slug-0001"
MATERIALS_URL = f"{SITE_URL}/m/{SLUG}"
WEBHOOK = "/telegram/webhook"
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
# The bot group set, the materials page on: what every bot test starts from.
BOT_SITE_ENV = {**BOT_ENV, "MATERIALS_SLUG": SLUG}
NO_BOT = dict.fromkeys(BOT_ENV)
# JSON nested this deep makes json give up with RecursionError, not ValueError, on any thread
# (a thread of the test client has a larger stack than the main one).
TOO_DEEP = 1_000_000

# Ids easy to find in a log, unlike 7 or 8.
USER = TelegramAccount(987654321, "secret_user_name")
OTHER = TelegramAccount(987650001, "other_user_name")
MEMBER = ChatMember("member")
LEFT = ChatMember("left")

# Situations of docs/copy.md, section 8 (the first column of the table).
MATERIALS = "Telegram підключено, людина підписана на канал"
NOT_SUBSCRIBED = "Telegram підключено, людина не підписана"
STILL_NOT_SUBSCRIBED = "Повторна перевірка: досі не підписаний"
CHECK_FAILED = "Не вдалося перевірити підписку"
EXPIRED = "Посилання невідоме або застаріле"
LINK_USED = "Посилання з екрана вже використав інший обліковий запис"
REGISTRATION_TAKEN = "Реєстрацію прив'язано до іншого Telegram (посилання з екрана)"
TELEGRAM_TAKEN = "Цей Telegram прив'язано до іншої реєстрації (посилання з екрана)"
TRANSFERRED = "Прив'язку перенесено посиланням із листа"
WELCOME = "/start без посилання, Telegram не підключено"


@dataclass(frozen=True, slots=True)
class Expected:
    """A message of section 8 with the values filled in, and the labels of its buttons."""

    text: str
    buttons: tuple[str, ...]


def bot_copy(materials_url: str = MATERIALS_URL) -> dict[str, Expected]:
    """Every row of the table of docs/copy.md, section 8, by situation."""
    rows = [line for line in copy.section("8").splitlines() if line.startswith("|")][2:]
    found: dict[str, Expected] = {}
    for row in rows:
        situation, text, buttons = (copy.plain(cell) for cell in row.strip().strip("|").split("|"))
        filled = text.replace("{site_url}", SITE_URL).replace("{materials_url}", materials_url)
        labels = () if buttons == "—" else tuple(label.strip() for label in buttons.split("·"))
        found[situation] = Expected(filled, labels)
    assert found, "no rows in section 8"
    return found


COPY = bot_copy()


def said(sent: list[SentMessage]) -> list[str]:
    """The texts the bot sent, in order."""
    return [message.text for message in sent]


def expected(*situations: str) -> list[str]:
    return [COPY[situation].text for situation in situations]


def labels(message: SentMessage) -> tuple[str, ...]:
    return tuple(button.text for row in message.buttons for button in row)


def buttons(message: SentMessage) -> list[Button]:
    return [button for row in message.buttons for button in row]


# --- Telegram updates ---------------------------------------------------------------------------

_update_ids = itertools.count(1)


def user_of(account: TelegramAccount) -> dict[str, Any]:
    user: dict[str, Any] = {"id": account.user_id, "is_bot": False, "first_name": "Visitor"}
    if account.username is not None:
        user["username"] = account.username
    return user


def message_update(
    account: TelegramAccount,
    text: str,
    *,
    chat_type: str = "private",
    chat_id: int | None = None,
    kind: str = "message",
) -> dict[str, Any]:
    """An update with a text message from ``account``; in a private chat its id is the user's."""
    return {
        "update_id": next(_update_ids),
        kind: {
            "message_id": 1,
            "date": 1_792_000_000,
            "from": user_of(account),
            "chat": {"id": account.user_id if chat_id is None else chat_id, "type": chat_type},
            "text": text,
        },
    }


def start_update(account: TelegramAccount, payload: str | None = None) -> dict[str, Any]:
    return message_update(account, "/start" if payload is None else f"/start {payload}")


def recheck_update(
    account: TelegramAccount, *, data: str = RECHECK, chat_type: str = "private"
) -> dict[str, Any]:
    """The button «Перевірити ще раз» pressed under a message of the bot."""
    return {
        "update_id": next(_update_ids),
        "callback_query": {
            "id": f"callback-{next(_update_ids)}",
            "from": user_of(account),
            "chat_instance": "1",
            "data": data,
            "message": {
                "message_id": 2,
                "date": 1_792_000_000,
                "chat": {"id": account.user_id, "type": chat_type},
                "text": "…",
            },
        },
    }


def callback_update(
    account: TelegramAccount, data: str, *, chat_type: str = "private", chat_id: int | None = None
) -> dict[str, Any]:
    """Any button of the bot pressed; under a post of the channel when ``chat_type`` says so."""
    update = recheck_update(account, data=data, chat_type=chat_type)
    if chat_id is not None:
        update["callback_query"]["message"]["chat"]["id"] = chat_id
    return update


# --- Telegram with failures ------------------------------------------------------------------


@dataclass
class Telegram(FakeMessenger):
    """``FakeMessenger`` whose methods fail as scripted: ``failures[method]`` holds what the next
    calls raise in turn (``None``: that call works). Remembers the channels it was asked about
    and every call, failed ones too (``calls``)."""

    failures: dict[str, list[Exception | None]] = field(default_factory=dict)
    channels: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

    def send_message(
        self,
        chat_id: int | str,
        text: str,
        buttons: Any = (),
        *,
        html: bool = False,
        preview: bool = True,
    ) -> None:
        self._script("send_message")
        super().send_message(chat_id, text, buttons, html=html, preview=preview)

    def answer_callback(
        self, callback_id: str, text: str | None = None, show_alert: bool = False
    ) -> None:
        self._script("answer_callback")
        super().answer_callback(callback_id, text, show_alert)

    def channel_member(self, channel: str, user_id: int) -> ChatMember:
        self.channels.append(channel)
        self._script("channel_member")
        return super().channel_member(channel, user_id)

    def set_webhook(self, url: str, secret: str, allowed_updates: Any) -> None:
        self._script("set_webhook")
        super().set_webhook(url, secret, allowed_updates)

    def _script(self, method: str) -> None:
        self.calls.append(method)
        queue = self.failures.get(method)
        if queue:
            error = queue.pop(0)
            if error is not None:
                raise error


class StuckTelegram(FakeMessenger):
    """Telegram that does not answer ``getChatMember`` until ``release``; counts who waits."""

    def __init__(self, members: Mapping[int, ChatMember] | None = None) -> None:
        super().__init__(members=dict(members or {}))
        self.released = threading.Event()
        self._lock = threading.Lock()
        self.threads: list[str] = []

    @property
    def waiting(self) -> int:
        with self._lock:
            return len(self.threads)

    def channel_member(self, channel: str, user_id: int) -> ChatMember:
        with self._lock:
            self.threads.append(threading.current_thread().name)
        self.released.wait(timeout=20)
        return super().channel_member(channel, user_id)

    def release(self) -> None:
        self.released.set()


class BlockedTelegram(FakeMessenger):
    """Telegram that does not answer ``setWebhook`` until ``release``; ``calling`` is set once
    the registration has asked."""

    def __init__(self) -> None:
        super().__init__()
        self.calling = threading.Event()
        self.released = threading.Event()

    def set_webhook(self, url: str, secret: str, allowed_updates: Any) -> None:
        self.calling.set()
        self.released.wait(timeout=10)
        super().set_webhook(url, secret, allowed_updates)

    def release(self) -> None:
        self.released.set()


# --- the pause between attempts --------------------------------------------------------------


@dataclass
class FakePause:
    """``Pause`` that never waits: it remembers the seconds asked for.

    After ``stop`` every wait says the application stops; ``stops_at`` stops it during that
    wait (1: the first one).
    """

    stops_at: int | None = None
    waited: list[float] = field(default_factory=list)
    stopped: bool = False

    def wait(self, seconds: float) -> bool:
        self.waited.append(seconds)
        if len(self.waited) == self.stops_at:
            self.stopped = True
        return not self.stopped

    def stop(self) -> None:
        self.stopped = True


def wait_until(condition: Callable[[], object], seconds: float = 5) -> None:
    """Poll ``condition`` until it holds: the webhook is registered on a thread of its own."""
    deadline = time.monotonic() + seconds
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("the condition did not come true")
        time.sleep(0.01)


# --- the application -------------------------------------------------------------------------


@dataclass
class BotSite:
    client: TestClient
    engine: Engine
    settings: Settings
    messenger: FakeMessenger
    clock: FixedClock

    def post(self, update: object, *, secret: str | None = SECRET) -> httpx.Response:
        """``POST /telegram/webhook`` with ``update`` (a dict as JSON, bytes as they are)."""
        headers = {} if secret is None else {SECRET_HEADER: secret}
        if isinstance(update, bytes):
            return self.client.post(WEBHOOK, content=update, headers=headers)
        return self.client.post(WEBHOOK, json=update, headers=headers)

    def start(self, account: TelegramAccount, payload: str | None = None) -> httpx.Response:
        return self.post(start_update(account, payload))

    def recheck(self, account: TelegramAccount) -> httpx.Response:
        return self.post(recheck_update(account))

    @property
    def sent(self) -> list[SentMessage]:
        return self.messenger.sent

    def said(self) -> list[str]:
        return said(self.messenger.sent)

    def forget(self) -> None:
        """Forget what the bot sent so far."""
        self.messenger.sent.clear()

    def participant(self, participant_id: int) -> Participant:
        with Session(self.engine) as session:
            row = session.get(Participant, participant_id)
            assert row is not None
            return row

    def link_token(self, token: str) -> LinkToken:
        with Session(self.engine) as session:
            row = session.scalars(select(LinkToken).where(LinkToken.token == token)).one()
            return row

    def linked(self) -> dict[int, int]:
        """``tg_user_id → participant id`` of every linked participant."""
        with Session(self.engine) as session:
            rows = session.scalars(select(Participant).where(Participant.tg_user_id.is_not(None)))
            return {row.tg_user_id: row.id for row in rows if row.tg_user_id is not None}


# --- broken stores ---------------------------------------------------------------------------


def _failing(error: type[StorageError]) -> type:
    class Store:
        def __getattr__(self, name: str) -> Any:
            def fail(*args: object, **kwargs: object) -> None:
                raise error(name)

            return fail

    Store.__name__ = error.__name__.removeprefix("Storage") or "Failing"
    return Store


Unavailable = _failing(StorageUnavailable)  # the database is down
Conflicting = _failing(StorageConflict)
Failing = _failing(StorageError)  # a bug, not an outage


def app_log(caplog: pytest.LogCaptureFixture) -> str:
    """What the application logged."""
    return "\n".join(
        record.getMessage() for record in caplog.records if record.name.startswith("app.")
    )
