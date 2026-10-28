"""Helpers of the LLM tests: a model that answers as scripted, Telegram updates, the texts.

Nothing here reaches Claude API: the language model is a fake (``FakeModel``), and the client
of the adapter is a stand-in (``FakeClient``). The expected texts come from docs/copy.md,
section 12.4, read on their own (``llm_copy``), never from the application.
"""

import itertools
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.adapters.db.models import Participant
from app.core.entities import TelegramAccount
from app.core.llm.classification import Classification
from app.core.llm.ports import ModelReply, ModelRequest
from tests import copy_oracle as copy
from tests.conftest import BOT_ENV, LLM_ENV
from tests.fakes import FakeMessenger, FixedClock

SECRET = BOT_ENV["TELEGRAM_WEBHOOK_SECRET"]
API_KEY = LLM_ENV["ANTHROPIC_API_KEY"]
WEBHOOK = "/telegram/webhook"
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
SLUG = "Sentinel_Slug-0001"
BOT_SITE_ENV = {**BOT_ENV, "MATERIALS_SLUG": SLUG}

# Ids easy to find in a log, unlike 7 or 8.
USER = TelegramAccount(987654321, "secret_user_name")
OTHER = TelegramAccount(987650001, "other_user_name")


def llm_copy() -> dict[str, str]:
    """Every row of the table of docs/copy.md, section 12.4: situation → text."""
    return copy.table(copy.section("12.4"))


def row(prefix: str) -> str:
    """The text of the row whose situation starts with ``prefix``."""
    found = [value for key, value in llm_copy().items() if key.startswith(prefix)]
    assert len(found) == 1, f"{len(found)} rows start with {prefix!r}"
    return found[0]


def refusal() -> str:
    return row("Запитання поза базою знань")


def too_long(max_chars: int) -> str:
    return row("Повідомлення довше").replace("{max_chars}", str(max_chars))


def too_many() -> str:
    return row("Забагато запитань")


def failure() -> str:
    return row("Збій Claude API")


def tool_reply(
    answer: str = "Курс триває 15 занять.",
    *,
    in_knowledge_base: bool = True,
    level: str = "unknown",
    intent: str = "unknown",
    input_tokens: int = 1234,
    output_tokens: int = 56,
) -> ModelReply:
    """What the model gives when it calls the tool, as the adapter reads it."""
    return ModelReply(
        {
            "answer": answer,
            "in_knowledge_base": in_knowledge_base,
            "level": level,
            "intent": intent,
        },
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


@dataclass
class FakeModel:
    """``LanguageModel`` that returns the scripted replies in turn (the last one stays).

    An ``Exception`` in the script is raised. Every request is kept in ``requests``.
    """

    script: list[ModelReply | Exception] = field(default_factory=lambda: [tool_reply()])
    requests: list[ModelRequest] = field(default_factory=list)

    def complete(self, request: ModelRequest) -> ModelReply:
        self.requests.append(request)
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return item


@dataclass
class FakeClassifications:
    """``ClassificationStore`` in memory; ``linked`` are the Telegram ids that have a link."""

    linked: set[int] = field(default_factory=set)
    saved: list[tuple[int, Classification]] = field(default_factory=list)

    def save(self, telegram_user_id: int, classification: Classification) -> bool:
        if telegram_user_id not in self.linked:
            return False
        self.saved.append((telegram_user_id, classification))
        return True


# --- the client of the adapter -----------------------------------------------------------------


class FakeClient:
    """Stand-in for ``anthropic.Anthropic``: ``messages.create`` keeps its arguments and
    returns the scripted message, or raises the scripted error."""

    def __init__(self, result: object | Exception) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def api_message(
    *blocks: object, stop_reason: str = "tool_use", input_tokens: int = 10, output_tokens: int = 5
) -> object:
    """A message of the API: blocks of ``thinking``, ``text``, ``tool_use`` and the usage."""
    return SimpleNamespace(
        content=list(blocks),
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def block(kind: str, **fields: object) -> object:
    return SimpleNamespace(type=kind, **fields)


# --- Telegram updates --------------------------------------------------------------------------

_update_ids = itertools.count(1)


def message_update(
    account: TelegramAccount, message_text: str, *, chat_type: str = "private"
) -> object:
    return {
        "update_id": next(_update_ids),
        "message": {
            "message_id": 1,
            "date": 1_792_000_000,
            "from": {"id": account.user_id, "is_bot": False, "first_name": "Visitor"},
            "chat": {"id": account.user_id, "type": chat_type},
            "text": message_text,
        },
    }


# --- the application ---------------------------------------------------------------------------


@dataclass
class LlmSite:
    client: TestClient
    engine: Engine
    messenger: FakeMessenger
    clock: FixedClock
    model: FakeModel

    def post(self, update: object) -> httpx.Response:
        return self.client.post(WEBHOOK, json=update, headers={SECRET_HEADER: SECRET})

    def say(self, account: TelegramAccount, message_text: str) -> httpx.Response:
        """A free-text message of ``account`` to the bot."""
        return self.post(message_update(account, message_text))

    def said(self) -> list[str]:
        return [message.text for message in self.messenger.sent]

    def extra(self, participant_id: int) -> dict[str, object] | None:
        with Session(self.engine) as session:
            found = session.get(Participant, participant_id)
            assert found is not None
            return found.extra

    def set_extra(self, participant_id: int, value: str) -> None:
        with Session(self.engine) as session, session.begin():
            session.execute(
                text("UPDATE participants SET extra = CAST(:v AS jsonb) WHERE id = :id"),
                {"v": value, "id": participant_id},
            )
