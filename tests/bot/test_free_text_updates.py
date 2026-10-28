"""Free text as a command of the bot (``parse_update(free_text=True)``, the LLM draft is on)."""

import json
from typing import Any

import pytest

from app.adapters.bot.updates import parse_update
from app.core.bot.commands import FreeText, Start
from app.core.entities import TelegramAccount
from tests.bot.helpers import USER, message_update


def body(update: object) -> bytes:
    return json.dumps(update).encode()


def test_text_is_ignored_unless_asked_for() -> None:
    assert parse_update(body(message_update(USER, "Скільки занять?"))) is None


def test_text_is_a_free_text_command_when_asked_for() -> None:
    update = message_update(USER, "  Скільки занять?  ")

    command = parse_update(body(update), free_text=True)

    assert command == FreeText(USER.user_id, USER, "Скільки занять?")


@pytest.mark.parametrize("text", ["/help", "/stats@some_bot now", " /help", "", "   "])
def test_commands_and_blank_text_are_not_free_text(text: str) -> None:
    assert parse_update(body(message_update(USER, text)), free_text=True) is None


def test_start_stays_start() -> None:
    command = parse_update(body(message_update(USER, "/start abc")), free_text=True)

    assert command == Start(USER.user_id, TelegramAccount(USER.user_id, USER.username), "abc")


def test_a_group_and_a_bot_are_not_free_text() -> None:
    group = message_update(USER, "Скільки занять?", chat_type="group")
    from_bot: dict[str, Any] = message_update(USER, "Скільки занять?")
    from_bot["message"]["from"]["is_bot"] = True

    assert parse_update(body(group), free_text=True) is None
    assert parse_update(body(from_bot), free_text=True) is None
