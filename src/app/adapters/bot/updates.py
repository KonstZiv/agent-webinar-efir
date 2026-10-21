"""Telegram updates of the webhook as commands of the core (``app.core.bot.commands``).

https://core.telegram.org/bots/api#update

Only ``message`` with ``/start`` and ``callback_query`` with the bot's button count, and only in
private chats (docs/requirements.md, section 7); everything else is ``None``, and the webhook
answers it with 200 so that Telegram does not send it again. Nothing is trusted: a body that
does not parse and a field of an unexpected type make the update ``None`` too. A username the
column ``tg_username`` (``varchar(64)``) could not hold is left out; the numeric id is the
identity anyway.
"""

import json
import re

from app.core.bot.commands import Command, Recheck, Start
from app.core.bot.replies import RECHECK
from app.core.entities import TelegramAccount

PRIVATE = "private"
START = "/start"
_USERNAME = re.compile(r"[A-Za-z0-9_]{1,64}")

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
        return _start(_object(update["message"]))
    if "callback_query" in update:
        return _recheck(_object(update["callback_query"]))
    return None


def _start(message: Json | None) -> Start | None:
    if message is None:
        return None
    chat_id = _private_chat(message)
    account = _account(message.get("from"))
    text = message.get("text")
    if chat_id is None or account is None or not isinstance(text, str):
        return None
    command, _, rest = text.strip().partition(" ")
    if command != START and not command.startswith(f"{START}@"):
        return None
    return Start(chat_id, account, rest.strip() or None)


def _recheck(callback: Json | None) -> Recheck | None:
    if callback is None or callback.get("data") != RECHECK:
        return None
    message = _object(callback.get("message"))
    chat_id = _private_chat(message) if message is not None else None
    account = _account(callback.get("from"))
    callback_id = callback.get("id")
    if chat_id is None or account is None or not isinstance(callback_id, str):
        return None
    return Recheck(chat_id, account, callback_id)


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
