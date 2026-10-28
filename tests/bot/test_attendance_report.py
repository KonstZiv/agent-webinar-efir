"""``/checkin_report``: counts, ratings and questions without addresses; long reports in parts."""

import pytest

from tests.bot.attendance import (
    GROUP,
    OTHER_GROUP,
    ROWS,
    TEACHER,
    TEACHER_ENV,
    add_checkin,
    add_mark,
    checkin_command,
    say,
)
from tests.bot.conftest import BotSiteFactory
from tests.bot.helpers import BotSite, Telegram
from tests.conftest import ParticipantFactory

TELEGRAM_LIMIT = 4096


@pytest.fixture
def site(bot_site_factory: BotSiteFactory) -> BotSite:
    return bot_site_factory(messenger=Telegram(), **TEACHER_ENV)


def report_text(**values: object) -> str:
    text = say("/checkin_report")
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    assert "{" not in text, text
    return text


def test_the_report_has_counts_ratings_and_questions_without_addresses(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    checkin = add_checkin(site, "AB23", GROUP)
    add_checkin(site, "CD34", OTHER_GROUP)  # a later one of another group
    people = [participant_factory(f"person{n}@example.com") for n in range(4)]
    add_mark(site, checkin.id, people[0].id, source="site", rating=5, question="Why?")
    add_mark(site, checkin.id, people[1].id, source="telegram", rating=4)
    add_mark(site, checkin.id, people[2].id, source="telegram", rating=4, question="And how?")
    add_mark(site, checkin.id, people[3].id, source="site")

    checkin_command(site, f"/checkin_report {GROUP}")

    [message] = site.sent
    assert message.chat_id == TEACHER.user_id
    assert message.text == report_text(
        id=checkin.id,
        lesson_date="21.10.2026",
        group=GROUP,
        attended=4,
        site=2,
        telegram=2,
        r5=1,
        r4=2,
        r3=0,
        r2=0,
        r1=0,
        average="4.3",
        questions_count=2,
        questions="\n1. Why?\n2. And how?",
    )
    assert "@example.com" not in message.text and "person" not in message.text


def test_a_report_without_marks_has_no_average_and_no_questions(site: BotSite) -> None:
    checkin = add_checkin(site, "AB23", GROUP)

    checkin_command(site, f"/checkin_report {GROUP}")

    [message] = site.sent
    assert message.text == report_text(
        id=checkin.id,
        lesson_date="21.10.2026",
        group=GROUP,
        attended=0,
        site=0,
        telegram=0,
        r5=0,
        r4=0,
        r3=0,
        r2=0,
        r1=0,
        average="—",
        questions_count=0,
        questions="немає",
    )


def test_the_report_without_a_group_is_of_the_latest_check_in(site: BotSite) -> None:
    add_checkin(site, "AB23", GROUP)
    latest = add_checkin(site, "CD34", OTHER_GROUP)

    checkin_command(site, "/checkin_report")

    assert f"#{latest.id}" in site.sent[0].text and OTHER_GROUP in site.sent[0].text


def test_the_report_of_a_group_is_of_its_latest_check_in(site: BotSite) -> None:
    add_checkin(site, "AB23", GROUP)
    latest = add_checkin(site, "CD34", GROUP)
    add_checkin(site, "EF45", OTHER_GROUP)

    checkin_command(site, f"/checkin_report {GROUP}")

    assert f"#{latest.id}," in site.sent[0].text


def test_a_long_report_comes_in_several_messages_without_cutting(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    checkin = add_checkin(site, "AB23", GROUP)
    questions = []
    for number in range(20):
        person = participant_factory(f"person{number}@example.com")
        question = f"Q{number:02d} " + "я" * 480  # Cyrillic counts as one character each
        questions.append(question)
        add_mark(site, checkin.id, person.id, question=question)

    checkin_command(site, f"/checkin_report {GROUP}")

    parts = [message.text for message in site.sent]
    assert len(parts) > 1
    assert all(len(part) <= TELEGRAM_LIMIT for part in parts)
    assert {message.chat_id for message in site.sent} == {TEACHER.user_id}
    whole = "\n".join(parts)
    assert whole.startswith(f"Чек-ін #{checkin.id}, заняття 21.10.2026")
    assert "Запитання (20):" in whole
    for number, question in enumerate(questions, start=1):
        assert f"\n{number}. {question}" in whole


def test_the_rows_of_the_report_in_the_copy_are_the_ones_used() -> None:
    assert "{questions}" in ROWS["/checkin_report"][0]
