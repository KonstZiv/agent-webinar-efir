"""What a person asks the bot, read from a Telegram update (``app.adapters.bot.updates``).

Only private chats give commands; in them the chat id is the user's id, but the core keeps
both, as Telegram sends them.
"""

from dataclasses import dataclass

from app.core.entities import TelegramAccount


@dataclass(frozen=True, slots=True)
class Start:
    """``/start``; ``payload`` is the text after it (the token of a link), ``None`` if empty."""

    chat_id: int
    account: TelegramAccount
    payload: str | None = None


@dataclass(frozen=True, slots=True)
class Recheck:
    """The button «Перевірити ще раз» under a message of the bot."""

    chat_id: int
    account: TelegramAccount
    callback_id: str


@dataclass(frozen=True, slots=True)
class FreeText:
    """A text that is not a command; read only when the LLM draft is on (staging)."""

    chat_id: int
    account: TelegramAccount
    text: str


type Command = Start | Recheck | FreeText
