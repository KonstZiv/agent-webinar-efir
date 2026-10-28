"""Telegram updates of the webhook as commands of the core (``app.core.bot.commands``).

https://core.telegram.org/bots/api#update

Only ``message`` and ``callback_query`` count, and only in private chats (docs/requirements.md,
section 7) — but for the button «Я на занятті» under a post of the channel; everything else is
``None``, and the webhook answers it with 200 so that Telegram does not send it again. A message
is ``/start``, a command of the teacher (``/checkin``, ``/checkin_close``, ``/checkin_report``)
or, when it is not a command at all, a text that may be a question to the trainer. A button is
«Перевірити ще раз», «Я на занятті» (``checkin:<id>``), a rating (``rate:<id>:<1–5>``) or a group
to open (``open:<group>``). Nothing is trusted: a body that does not parse and a field of an
unexpected type make the update ``None`` too. A username the column ``tg_username``
(``varchar(64)``) could not hold is left out; the numeric id is the identity anyway.
"""

import json
import re

from app.core.bot.attendance import CHECKIN, CLOSE, GROUP_PATTERN, REPORT
from app.core.bot.attendance_replies import OPEN_PREFIX, PRESS_PREFIX, RATE_PREFIX
from app.core.bot.commands import (
    Command,
    PickGroup,
    Press,
    Question,
    Rate,
    Recheck,
    Start,
    TeacherCommand,
)
from app.core.bot.replies import RECHECK
from app.core.entities import TelegramAccount

PRIVATE = "private"
CHANNEL = "channel"
START = "/start"
TEACHER_COMMANDS = frozenset({CHECKIN, CLOSE, REPORT})
_USERNAME = re.compile(r"[A-Za-z0-9_]{1,64}")
_ID = r"[0-9]{1,18}"  # a check-in id, within a bigint
_PRESS = re.compile(rf"{PRESS_PREFIX}:({_ID})")
_RATE = re.compile(rf"{RATE_PREFIX}:({_ID}):([1-5])")
_OPEN = re.compile(rf"{OPEN_PREFIX}:({GROUP_PATTERN})")

type Json = dict[str, object]


def parse_update(body: bytes) -> Command | None:
    """The command in a webhook body, or ``None`` for anything the bot does not handle.

    >>> parse_update(b'{"update_id": 1, "edited_message": {}}') is None
    True
    """
    try:
        update = json.loads(body)
    except (ValueError, RecursionError):  # not JSON, not UTF-8, too many digits, nested too deep
        return None
    if not isinstance(update, dict):
        return None
    if "message" in update:
        return _message(_object(update["message"]))
    if "callback_query" in update:
        return _button(_object(update["callback_query"]))
    return None


def _message(message: Json | None) -> Command | None:
    if message is None:
        return None
    chat_id = _private_chat(message)
    account = _account(message.get("from"))
    text = message.get("text")
    if chat_id is None or account is None or not isinstance(text, str):
        return None
    words = text.strip().split(maxsplit=1)
    if not words:
        return None
    command, rest = words[0], (words[1].strip() if len(words) > 1 else "")
    if not command.startswith("/"):
        return Question(chat_id, account.user_id, text.strip())
    name = command.partition("@")[0]
    if name == START:
        return Start(chat_id, account, rest or None)
    if name[1:] in TEACHER_COMMANDS:
        return TeacherCommand(chat_id, account.user_id, name[1:], rest)
    return None


def _button(callback: Json | None) -> Command | None:
    if callback is None:
        return None
    data = callback.get("data")
    message = _object(callback.get("message"))
    account = _account(callback.get("from"))
    callback_id = callback.get("id")
    if (
        not isinstance(data, str)
        or message is None
        or account is None
        or not isinstance(callback_id, str)
    ):
        return None
    chat = _object(message.get("chat"))
    chat_type = chat.get("type") if chat is not None else None
    chat_id = _private_chat(message)
    if press := _PRESS.fullmatch(data):
        # Under the post of the channel, or in a private chat.
        if chat_type not in (PRIVATE, CHANNEL):
            return None
        return Press(account.user_id, callback_id, int(press.group(1)))
    if chat_id is None:
        return None
    if data == RECHECK:
        return Recheck(chat_id, account, callback_id)
    if rate := _RATE.fullmatch(data):
        return Rate(chat_id, account.user_id, callback_id, int(rate.group(1)), int(rate.group(2)))
    if group := _OPEN.fullmatch(data):
        return PickGroup(chat_id, account.user_id, callback_id, group.group(1))
    return None


def _private_chat(message: Json) -> int | None:
    chat = _object(message.get("chat"))
    if chat is None or chat.get("type") != PRIVATE:
        return None
    return _integer(chat.get("id"))


def _account(value: object) -> TelegramAccount | None:
    user = _object(value)
    if user is None or user.get("is_bot") is True:
        return None
    user_id = _integer(user.get("id"))
    if user_id is None:
        return None
    username = user.get("username")
    kept = username if isinstance(username, str) and _USERNAME.fullmatch(username) else None
    return TelegramAccount(user_id, kept)


def _object(value: object) -> Json | None:
    return value if isinstance(value, dict) else None


def _integer(value: object) -> int | None:
    """An integer of JSON; ``True`` is not one, although Python counts it as an ``int``."""
    return value if type(value) is int else None
