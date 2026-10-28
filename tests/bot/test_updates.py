"""Updates of Telegram as the bot reads them: commands, buttons and texts, in private chats only."""

import json
from typing import Any

import pytest

from app.adapters.bot.updates import parse_update
from app.core.bot.commands import Code, PickGroup, Question, Rate, Recheck, Start, TeacherCommand
from app.core.entities import TelegramAccount
from tests.bot.helpers import (
    TOO_DEEP,
    USER,
    callback_update,
    message_update,
    recheck_update,
    start_update,
)


def parse(update: object) -> object:
    return parse_update(json.dumps(update).encode())


def test_start_without_a_payload() -> None:
    assert parse(start_update(USER)) == Start(USER.user_id, USER, None)


def test_start_with_a_token() -> None:
    assert parse(start_update(USER, "Tok-en_1")) == Start(USER.user_id, USER, "Tok-en_1")


@pytest.mark.parametrize(
    ("text", "payload"),
    [
        ("/start@sentinel_webinar_bot Tok-en_1", "Tok-en_1"),
        ("/start   Tok-en_1  ", "Tok-en_1"),
        ("/start ", None),
        ("/start@sentinel_webinar_bot", None),
        ("/start two words", "two words"),  # not a token: the dialog answers as to rule 1
    ],
)
def test_forms_of_start(text: str, payload: str | None) -> None:
    assert parse(message_update(USER, text)) == Start(USER.user_id, USER, payload)


def test_the_button_check_again() -> None:
    update = recheck_update(USER)
    callback_id = update["callback_query"]["id"]

    assert parse(update) == Recheck(USER.user_id, USER, callback_id)


def test_an_account_without_a_username() -> None:
    account = TelegramAccount(USER.user_id)

    assert parse(start_update(account)) == Start(USER.user_id, account, None)


@pytest.mark.parametrize("username", ["bad name", "x" * 65, "ім'я", ""])
def test_a_username_the_column_cannot_hold_is_left_out(username: str) -> None:
    update = start_update(USER)
    update["message"]["from"]["username"] = username

    assert parse(update) == Start(USER.user_id, TelegramAccount(USER.user_id), None)


@pytest.mark.parametrize("chat_type", ["group", "supergroup", "channel"])
def test_chats_other_than_private_are_ignored(chat_type: str) -> None:
    assert parse(message_update(USER, "/start Tok-en_1", chat_type=chat_type)) is None
    assert parse(recheck_update(USER, chat_type=chat_type)) is None


@pytest.mark.parametrize("kind", ["edited_message", "channel_post", "business_message"])
def test_other_kinds_of_message_are_ignored(kind: str) -> None:
    assert parse(message_update(USER, "/start Tok-en_1", kind=kind)) is None


@pytest.mark.parametrize(
    "update",
    [
        {"update_id": 1, "my_chat_member": {"chat": {"id": 1, "type": "private"}}},
        {"update_id": 1, "inline_query": {"id": "1", "query": "/start"}},
        {"update_id": 1},
    ],
    ids=["my_chat_member", "inline_query", "empty"],
)
def test_other_updates_are_ignored(update: dict[str, Any]) -> None:
    assert parse(update) is None


@pytest.mark.parametrize("text", ["/help", "/started", "/Start x", "/checkins", "/checkin_x"])
def test_other_commands_are_ignored(text: str) -> None:
    assert parse(message_update(USER, text)) is None


@pytest.mark.parametrize("text", ["hello", "start", " a question\nin two lines "])
def test_a_text_that_is_not_a_command_is_a_possible_question(text: str) -> None:
    assert parse(message_update(USER, text)) == Question(USER.user_id, USER.user_id, text.strip())


def test_an_empty_text_is_ignored() -> None:
    assert parse(message_update(USER, "   ")) is None


@pytest.mark.parametrize(
    ("text", "name", "arguments"),
    [
        ("/checkin", "checkin", ""),
        ("/checkin cbs-2026-10", "checkin", "cbs-2026-10"),
        ("/checkin   cbs-2026-10   15 ", "checkin", "cbs-2026-10   15"),
        ("/checkin@sentinel_webinar_bot cbs-2026-10", "checkin", "cbs-2026-10"),
        ("/checkin_close", "checkin_close", ""),
        ("/checkin_close cbs-2026-10", "checkin_close", "cbs-2026-10"),
        ("/checkin_report open-2026-10", "checkin_report", "open-2026-10"),
    ],
)
def test_the_commands_of_the_teacher(text: str, name: str, arguments: str) -> None:
    assert parse(message_update(USER, text)) == TeacherCommand(
        USER.user_id, USER.user_id, name, arguments
    )


def test_the_commands_of_the_teacher_are_read_in_private_chats_only() -> None:
    update = message_update(USER, "/checkin cbs-2026-10", chat_type="supergroup", chat_id=-100555)

    assert parse(update) is None


@pytest.mark.parametrize(
    ("text", "code"), [("AB23", "AB23"), (" 5ean ", "5EAN"), ("zz9k\n", "ZZ9K")]
)
def test_a_text_of_four_characters_of_the_alphabet_is_a_code(text: str, code: str) -> None:
    assert parse(message_update(USER, text)) == Code(USER.user_id, USER.user_id, code)


@pytest.mark.parametrize("text", ["ABCDE", "AB2", "AB 23", "AB2!", "0OI1", "ЯBCD", "ßAB3", "ǅAB3"])
def test_other_texts_are_not_a_code(text: str) -> None:
    assert parse(message_update(USER, text)) == Question(USER.user_id, USER.user_id, text.strip())


def test_a_code_in_a_group_chat_is_ignored() -> None:
    update = message_update(USER, "AB23", chat_type="supergroup", chat_id=-100555)

    assert parse(update) is None


@pytest.mark.parametrize("chat_type", ["private", "channel", "group", "supergroup"])
def test_the_old_button_of_a_check_in_is_ignored(chat_type: str) -> None:
    assert parse(callback_update(USER, "checkin:42", chat_type=chat_type)) is None


def test_the_rating_button() -> None:
    update = callback_update(USER, "rate:42:5")

    assert parse(update) == Rate(USER.user_id, USER.user_id, update["callback_query"]["id"], 42, 5)


def test_the_button_of_a_group() -> None:
    update = callback_update(USER, "open:cbs-2026-10")

    assert parse(update) == PickGroup(
        USER.user_id, USER.user_id, update["callback_query"]["id"], "cbs-2026-10"
    )


@pytest.mark.parametrize(
    "data",
    [
        "checkin:",
        "checkin:x",
        "checkin:1234567890123456789",  # 19 digits: beyond a bigint
        "checkin:-1",
        "checkin:1 ",
        "rate:42:0",
        "rate:42:6",
        "rate:42:55",
        "rate:42",
        "open:",
        "open:X",
        "open:a",
        "open:cbs_2026",
        f"open:{'a' * 33}",
        "close:1",
    ],
)
def test_malformed_data_of_a_button_is_ignored(data: str) -> None:
    assert parse(callback_update(USER, data)) is None
    assert parse(callback_update(USER, data, chat_type="channel")) is None


def test_the_rating_and_group_buttons_are_for_private_chats_only() -> None:
    assert parse(callback_update(USER, "rate:42:5", chat_type="channel")) is None
    assert parse(callback_update(USER, "open:cbs-2026-10", chat_type="channel")) is None


def test_a_button_without_data_is_ignored() -> None:
    update = callback_update(USER, "rate:42:5")
    del update["callback_query"]["data"]

    assert parse(update) is None


def test_a_button_of_someone_else_is_ignored() -> None:
    assert parse(recheck_update(USER, data="something-else")) is None


def test_a_button_without_its_message_is_ignored() -> None:
    update = recheck_update(USER)
    del update["callback_query"]["message"]

    assert parse(update) is None


def broken(path: tuple[str, ...], value: object) -> dict[str, Any]:
    update = start_update(USER, "Tok-en_1")
    target = update
    for key in path[:-1]:
        target = target[key]
    if value is DELETE:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return update


DELETE = object()


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("message", "from"), DELETE),
        (("message", "from", "is_bot"), True),
        (("message", "from", "id"), "987654321"),
        (("message", "from", "id"), True),
        (("message", "chat"), DELETE),
        (("message", "chat", "id"), None),
        (("message", "text"), DELETE),
        (("message", "text"), 42),
        (("message",), "text"),
    ],
    ids=lambda part: ".".join(part) if isinstance(part, tuple) else repr(part),
)
def test_updates_of_an_unexpected_shape_are_ignored(path: tuple[str, ...], value: object) -> None:
    assert parse(broken(path, value)) is None


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not json",
        b"\xff\xfe",
        b"[]",
        b"null",
        b'"text"',
        b"[" * TOO_DEEP + b"]" * TOO_DEEP,
        b'{"a":' * TOO_DEEP + b"1" + b"}" * TOO_DEEP,
        b'{"update_id": 1, "message": ' + b"[" * TOO_DEEP + b"]" * TOO_DEEP + b"}",
        b'{"update_id": ' + b"1" * 5000 + b"}",
    ],
    ids=[
        "empty",
        "not-json",
        "not-utf-8",
        "list",
        "null",
        "string",
        "nested-lists",
        "nested-objects",
        "nested-message",
        "too-many-digits",
    ],
)
def test_a_body_that_is_not_an_update_is_ignored(body: bytes) -> None:
    assert parse_update(body) is None
