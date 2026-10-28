"""``/checkin_report``: a narrow table (message 1, HTML) and the questions (message 2, plain)."""

from dataclasses import dataclass, field
from datetime import date

import pytest

from app.core.bot.attendance_replies import report_table as render_table
from tests.bot.attendance import (
    GROUP,
    OTHER_GROUP,
    REPORT_LABELS,
    TABLE_WIDTH,
    TEACHER,
    TEACHER_ENV,
    add_checkin,
    add_mark,
    checkin_command,
    report_questions_head,
    report_table,
)
from tests.bot.conftest import BotSiteFactory
from tests.bot.helpers import BotSite, Telegram
from tests.conftest import ParticipantFactory

TELEGRAM_LIMIT = 4096


@pytest.fixture
def site(bot_site_factory: BotSiteFactory) -> BotSite:
    return bot_site_factory(messenger=Telegram(), **TEACHER_ENV)


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

    table, questions = site.sent
    assert {message.chat_id for message in site.sent} == {TEACHER.user_id}
    assert table.html is True
    assert table.text == report_table(
        checkin, attended=4, site=2, telegram=2, ratings={5: 1, 4: 2}, average="4.3"
    )
    assert questions.html is False
    assert questions.text == report_questions_head(2) + "\n1. Why?\n2. And how?"
    assert all("@example.com" not in m.text and "person" not in m.text for m in site.sent)


def test_the_table_is_the_one_of_the_example(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    checkin = add_checkin(site, "AB23", "test", lesson_date=date(2026, 10, 28))
    add_mark(site, checkin.id, participant_factory("a@example.com").id, source="telegram", rating=4)

    checkin_command(site, "/checkin_report test")

    [table] = site.sent
    assert table.text == (
        "<pre>"
        f"Чек-ін #{checkin.id} · група test\n"
        "Заняття 28.10.2026\n"
        "────────────────────────\n"
        "Відмітились            1\n"
        "  на сайті             0\n"
        "  у Telegram           1\n"
        "────────────────────────\n"
        "Оцінки\n"
        "  5                    0\n"
        "  4 ██████████         1\n"
        "  3                    0\n"
        "  2                    0\n"
        "  1                    0\n"
        "Середня              4.0"
        "</pre>"
    )


def test_the_rows_with_numbers_and_the_separators_are_24_characters(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    checkin = add_checkin(site, "AB23", GROUP)
    for number, rating in enumerate([5, 5, 5, 3, 1, 1, 1, 1, 1, 1, 1, 1]):
        person = participant_factory(f"person{number}@example.com")
        add_mark(site, checkin.id, person.id, rating=rating)

    checkin_command(site, f"/checkin_report {GROUP}")

    [table] = site.sent
    lines = table.text.removeprefix("<pre>").removesuffix("</pre>").split("\n")
    body = [line for index, line in enumerate(lines) if index > 1 and index != 7]
    assert all(len(line) == TABLE_WIDTH for line in body)  # the headers may be longer
    assert lines[2] == lines[6] == "─" * TABLE_WIDTH
    assert lines[8].startswith("  5 ████ ")  # 3 of 8: round(10 × 3 / 8) = 4
    assert lines[10].startswith("  3 █ ")  # 1 of 8 rounds to 1: never less than one for n > 0
    assert lines[12].startswith("  1 ██████████ ")  # the biggest count has the full bar
    assert lines[9] == "  4" + " " * 20 + "0"  # no bar for zero


@dataclass
class Summary:
    """A report with a group that would break HTML if it were not escaped."""

    group: str | None = "<b>&"
    id: int = 1
    lesson_date: date = date(2026, 10, 28)
    attended: int = 0
    site: int = 0
    telegram: int = 0
    average: float | None = None
    ratings: dict[int, int] = field(default_factory=dict)
    questions: list[str] = field(default_factory=list)
    status: str = "found"


def test_the_values_in_the_table_are_escaped() -> None:
    table = render_table(Summary())  # type: ignore[arg-type]

    assert "<b>" not in table and "&lt;b&gt;&amp;" in table
    assert table.startswith("<pre>") and table.endswith("</pre>")


def test_a_report_without_marks_is_one_message_with_no_average(site: BotSite) -> None:
    checkin = add_checkin(site, "AB23", GROUP)

    checkin_command(site, f"/checkin_report {GROUP}")

    [table] = site.sent
    assert table.html is True
    assert table.text == report_table(checkin)
    assert table.text.endswith("—</pre>")


def test_the_report_without_a_group_is_of_the_latest_check_in(site: BotSite) -> None:
    add_checkin(site, "AB23", GROUP)
    latest = add_checkin(site, "CD34", OTHER_GROUP)

    checkin_command(site, "/checkin_report")

    assert f"#{latest.id} " in site.sent[0].text and OTHER_GROUP in site.sent[0].text


def test_the_report_of_a_group_is_of_its_latest_check_in(site: BotSite) -> None:
    add_checkin(site, "AB23", GROUP)
    latest = add_checkin(site, "CD34", GROUP)
    add_checkin(site, "EF45", OTHER_GROUP)

    checkin_command(site, f"/checkin_report {GROUP}")

    assert f"#{latest.id} " in site.sent[0].text


def test_a_question_with_markup_never_gets_into_the_html_message(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    checkin = add_checkin(site, "AB23", GROUP)
    person = participant_factory("person@example.com")
    add_mark(site, checkin.id, person.id, question="Is <b>this</b> & that fine?")

    checkin_command(site, f"/checkin_report {GROUP}")

    table, questions = site.sent
    assert table.html is True and "<b>" not in table.text and "Is " not in table.text
    assert questions.html is False
    assert "1. Is <b>this</b> & that fine?" in questions.text


def test_long_questions_come_in_several_plain_messages_without_cutting(
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

    table, *parts = site.sent
    assert table.html is True and table.text == report_table(checkin, attended=20, site=20)
    assert len(parts) > 1
    assert all(not part.html for part in parts)
    assert all(len(part.text) <= TELEGRAM_LIMIT for part in parts)
    assert {message.chat_id for message in site.sent} == {TEACHER.user_id}
    whole = "\n".join(part.text for part in parts)
    assert whole.startswith(report_questions_head(20))
    for number, question in enumerate(questions, start=1):
        assert f"\n{number}. {question}" in whole


def test_the_labels_of_the_report_in_the_copy_are_the_ones_used() -> None:
    assert REPORT_LABELS[0] == "Чек-ін #{id} · група {group}"
    assert REPORT_LABELS[7] == "Запитання ({questions_count}):"
