"""The bot's dialog: ``/start`` with a link, ``/start`` alone, the button «Перевірити ще раз».

The rules of ``/start <token>`` (docs/requirements.md, section 7), in this order:

1. the token is unknown or expired — «the link is out of date»;
2. a ``screen`` token already used: by this Telegram — the check; by another — a refusal;
3. the registration is linked to this Telegram — the check;
4. neither the registration nor this Telegram is linked — link, then the check;
5. one of them is linked elsewhere: an ``email`` token moves the link here (the email proves
   the mailbox), a ``screen`` token is refused (anyone who typed the address saw the screen).

A token counts as used when it made or confirmed a link (rules 3–5): ``claim`` for a single-use
``screen`` token, ``record_use`` for an ``email`` one. A refusal leaves it as it was.

Concurrent requests are settled by the stores' conditional statements: a link that loses a race
returns ``False`` or raises ``StorageConflict``, and the dialog reads the registration again and
answers by the rules. Other storage failures reach the caller: an outage is worth a retry of
the update, the rest is a bug. A 429 of Telegram on a message reaches the caller too (the update
is to be retried); any other failure to send is logged and the dialog goes on.
"""

import logging
import re
from dataclasses import dataclass
from enum import StrEnum

from app.core.bot.commands import Command, FreeText, Recheck
from app.core.bot.ports import FreeTextResponder, MessengerRateLimited
from app.core.bot.replies import Answer, Replies
from app.core.entities import ChatMember, LinkToken, Participant, TelegramAccount
from app.core.ports import (
    Clock,
    LinkTokenStore,
    Messenger,
    MessengerUnavailable,
    ParticipantStore,
    StorageConflict,
)

logger = logging.getLogger(__name__)

# A token as the site issues it; Telegram's ``start`` takes up to 64 of these characters.
_TOKEN = re.compile(r"[A-Za-z0-9_-]{1,64}")
_MEMBER_STATUSES = frozenset({"member", "administrator", "creator"})


def is_subscribed(member: ChatMember) -> bool:
    """Whether a status of ``getChatMember`` means a subscriber of the channel.

    >>> is_subscribed(ChatMember("administrator")), is_subscribed(ChatMember("restricted", True))
    (True, True)
    >>> is_subscribed(ChatMember("restricted")), is_subscribed(ChatMember("left"))
    (False, False)
    """
    if member.status == "restricted":
        return member.is_member is True
    return member.status in _MEMBER_STATUSES


class Linking(StrEnum):
    """What a command did to the link between Telegram and a registration."""

    NONE = "none"  # no link was asked for: /start alone, the button
    REFUSED = "refused"  # rules 1, 2 (another Telegram) and 5 for a screen token
    KEPT = "kept"  # rules 2 (this Telegram) and 3
    LINKED = "linked"  # rule 4
    TRANSFERRED = "transferred"  # rule 5 for an email token


@dataclass(frozen=True, slots=True)
class Outcome:
    """What happened and what the person got last; ``str`` is the line of the log."""

    linking: Linking
    answer: Answer

    def __str__(self) -> str:
        return f"{self.linking}, {self.answer}"


class BotDialog:
    """Handles one command of a person; storage errors other than races reach the caller."""

    def __init__(
        self,
        *,
        participants: ParticipantStore,
        tokens: LinkTokenStore,
        messenger: Messenger,
        clock: Clock,
        replies: Replies,
        channel: str,
        free_text: FreeTextResponder | None = None,
    ) -> None:
        self._free_text = free_text
        self._participants = participants
        self._tokens = tokens
        self._messenger = messenger
        self._clock = clock
        self._replies = replies
        self._channel = channel

    def handle(self, command: Command) -> Outcome:
        if isinstance(command, FreeText):
            return self._answer_text(command)
        if isinstance(command, Recheck):
            self._answer_button(command.callback_id)
            return Outcome(Linking.NONE, self._check(command.chat_id, command.account, True))
        if command.payload is None:
            return Outcome(Linking.NONE, self._check(command.chat_id, command.account))
        return self._start(command.chat_id, command.account, command.payload)

    def _answer_text(self, command: FreeText) -> Outcome:
        """The LLM draft answers a free text; without it the text is ignored.

        The answer is paid for, so a Telegram failure to send it (a 429 too) is only logged:
        a retry of the update would ask the model again.
        """
        outcome = Outcome(Linking.NONE, Answer.FREE_TEXT)
        if self._free_text is None:
            return outcome
        text = self._free_text.respond(command.account.user_id, command.text)
        try:
            self._messenger.send_message(command.chat_id, text)
        except MessengerUnavailable as error:
            logger.warning("Telegram message not sent: %s", type(error).__name__)
        return outcome

    def _start(self, chat_id: int, account: TelegramAccount, payload: str) -> Outcome:
        now = self._clock.now()
        token = self._tokens.find(payload) if _TOKEN.fullmatch(payload) else None
        if token is None or token.expires_at <= now:
            return self._refuse(chat_id, Answer.EXPIRED)
        if token.source == "screen" and token.used_at is not None:
            if token.used_by_tg_user_id != account.user_id:
                return self._refuse(chat_id, Answer.LINK_USED)
            return Outcome(Linking.KEPT, self._check(chat_id, account))
        participant = self._participants.by_id(token.participant_id)
        if participant is None:  # unsubscribed since the token was found
            return self._refuse(chat_id, Answer.EXPIRED)
        if participant.telegram is None:
            if self._link_if_free(participant.id, account):
                self._use(token, account)
                return Outcome(Linking.LINKED, self._check(chat_id, account))
            # Lost to a concurrent link: of this very Telegram (a double click) or of another.
            participant = self._participants.by_id(token.participant_id)
            if participant is None:
                return self._refuse(chat_id, Answer.EXPIRED)
        if _linked_to(participant, account):
            self._use(token, account)
            return Outcome(Linking.KEPT, self._check(chat_id, account))
        if token.source == "email":
            return self._transfer(chat_id, token, account)
        if participant.telegram is not None:
            return self._refuse(chat_id, Answer.REGISTRATION_TAKEN)
        return self._refuse(chat_id, Answer.TELEGRAM_TAKEN)

    def _link_if_free(self, participant_id: int, account: TelegramAccount) -> bool:
        """Rule 4; ``False`` when either side is linked, a race lost included."""
        try:
            return self._participants.link_telegram_if_free(
                participant_id, account, self._clock.now()
            )
        except StorageConflict:  # another registration took this Telegram at the same moment
            return False

    def _transfer(self, chat_id: int, token: LinkToken, account: TelegramAccount) -> Outcome:
        """Rule 5 for an email token: the link moves to the token's registration."""
        try:
            moved = self._participants.transfer_telegram(
                token.participant_id, account, self._clock.now()
            )
        except StorageConflict:  # another email link moved this Telegram at the same moment
            return self._refuse(chat_id, Answer.TELEGRAM_TAKEN)
        if not moved:
            return self._refuse(chat_id, Answer.EXPIRED)
        self._use(token, account)
        self._send(chat_id, Answer.TRANSFERRED)
        return Outcome(Linking.TRANSFERRED, self._check(chat_id, account))

    def _use(self, token: LinkToken, account: TelegramAccount) -> None:
        if token.source == "screen":
            self._tokens.claim(token.token, account.user_id, self._clock.now())
        else:
            self._tokens.record_use(token.token, account.user_id, self._clock.now())

    def _check(self, chat_id: int, account: TelegramAccount, recheck: bool = False) -> Answer:
        """The channel check for the registration this Telegram is linked to now."""
        participant = self._participants.by_telegram(account.user_id)
        if participant is None:
            return self._send(chat_id, Answer.WELCOME)
        try:
            member = self._messenger.channel_member(self._channel, account.user_id)
        except MessengerUnavailable:
            return self._send(chat_id, Answer.CHECK_FAILED)
        subscribed = is_subscribed(member)
        self._participants.set_channel_member(participant.id, account.user_id, subscribed)
        if subscribed:
            has_link = self._replies.has_materials
            return self._send(chat_id, Answer.MATERIALS if has_link else Answer.NO_MATERIALS_LINK)
        return self._send(
            chat_id, Answer.STILL_NOT_SUBSCRIBED if recheck else Answer.NOT_SUBSCRIBED
        )

    def _refuse(self, chat_id: int, answer: Answer) -> Outcome:
        return Outcome(Linking.REFUSED, self._send(chat_id, answer))

    def _send(self, chat_id: int, answer: Answer) -> Answer:
        reply = self._replies.reply(answer)
        try:
            self._messenger.send_message(chat_id, reply.text, reply.buttons)
        except MessengerRateLimited:
            raise
        except MessengerUnavailable:
            logger.warning("Telegram message not sent: %s", answer)
        return answer

    def _answer_button(self, callback_id: str) -> None:
        """Stop the button's spinner; without it the check still goes on."""
        try:
            self._messenger.answer_callback(callback_id)
        except MessengerUnavailable as error:
            logger.warning("Telegram button not answered: %s", type(error).__name__)


def _linked_to(participant: Participant, account: TelegramAccount) -> bool:
    return participant.telegram is not None and participant.telegram.user_id == account.user_id
