"""The attendance for the bot of Telegram: ``TelegramAttendance`` on the real scenarios and store.

The bot's own tests (tests/bot) go through the webhook with the same slice; here the answers of
the adapter are read directly, with the database underneath.
"""

from datetime import date, timedelta

import pytest

from app.adapters.checkin.keys import TELEGRAM
from app.adapters.checkin.telegram import TelegramAttendance
from app.core.entities import TelegramAccount
from tests.checkin.conftest import Site
from tests.checkin.helpers import ADMIN, GROUP, LESSON
from tests.conftest import ParticipantFactory

USER = TelegramAccount(555000111, "student_name")
OTHER = TelegramAccount(555000222, "other_name")
TODAY = date(2026, 10, 21)


@pytest.fixture
def telegram(site: Site) -> TelegramAttendance:
    service = site.client.app.state.container.services.get(TELEGRAM)  # type: ignore[attr-defined]
    assert isinstance(service, TelegramAttendance)
    return service


def assign(site: Site, group: str, email: str) -> None:
    """Put the registered address into the group through the admin API."""
    response = site.client.put(
        f"/admin/groups/{group}/members", json={"emails": [email]}, headers=ADMIN
    )
    assert response.status_code == 200


def test_the_key_is_the_name_the_bot_looks_for() -> None:
    assert TELEGRAM.name == "checkin.telegram"


# --- opening ----------------------------------------------------------------------------------


def test_open_stores_a_check_in_of_the_group(site: Site, telegram: TelegramAttendance) -> None:
    opened = telegram.open(TODAY, GROUP, 15)

    assert opened.status == "opened" and opened.group == GROUP
    [row] = site.checkins()
    assert (row.id, row.code) == (opened.id, opened.code)
    assert (row.group_code, row.lesson_date) == (GROUP, TODAY)
    assert row.closes_at - row.opened_at == timedelta(minutes=15)
    assert opened.closes_at == row.closes_at
    assert len(opened.code) == 4


def test_a_group_with_an_open_check_in_gets_no_second_one(
    site: Site, telegram: TelegramAttendance
) -> None:
    first = telegram.open(TODAY, GROUP, 20)

    second = telegram.open(TODAY, GROUP, 20)

    assert second.status == "open_exists"
    assert (second.id, second.code, second.closes_at) == (first.id, first.code, first.closes_at)
    assert len(site.checkins()) == 1


def test_another_group_and_a_check_in_made_by_the_admin_api_are_apart(
    site: Site, telegram: TelegramAttendance
) -> None:
    site.open(group="open-2026-10")
    site.open(group=None)

    assert telegram.open(TODAY, GROUP, 20).status == "opened"
    assert len(site.checkins()) == 3


def test_a_closed_check_in_lets_the_group_open_again(
    site: Site, telegram: TelegramAttendance
) -> None:
    telegram.open(TODAY, GROUP, 20)
    site.clock.advance(timedelta(minutes=20))

    assert telegram.open(TODAY, GROUP, 20).status == "opened"
    assert len(site.checkins()) == 2


def test_the_codes_of_open_check_ins_differ(site: Site, telegram: TelegramAttendance) -> None:
    codes = {telegram.open(TODAY, f"group-{number:02d}", 20).code for number in range(12)}

    assert len(codes) == 12


# --- known groups, closing, the report --------------------------------------------------------


def test_known_groups_come_from_members_and_check_ins_the_freshest_first(
    site: Site, telegram: TelegramAttendance, participant_factory: ParticipantFactory
) -> None:
    person = participant_factory("one@example.com")
    assign(site, "old-members", person.email)
    site.clock.advance(timedelta(days=1))
    site.open(group="cbs-2026-10")
    site.clock.advance(timedelta(days=1))
    assign(site, "new-members", person.email)
    site.open(group=None)  # no group, nothing to offer

    assert telegram.known_groups(8) == ["new-members", "cbs-2026-10", "old-members"]
    assert telegram.known_groups(2) == ["new-members", "cbs-2026-10"]


def test_a_group_of_members_and_of_check_ins_is_listed_once(
    site: Site, telegram: TelegramAttendance, participant_factory: ParticipantFactory
) -> None:
    person = participant_factory("one@example.com")
    assign(site, GROUP, person.email)
    site.open(group=GROUP)

    assert telegram.known_groups(8) == [GROUP]


def test_close_ends_the_open_check_in_of_the_group_and_counts_the_marks(
    site: Site, telegram: TelegramAttendance, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com", telegram=USER)
    opened = telegram.open(TODAY, GROUP, 20)
    telegram.mark_code(opened.code, USER.user_id)
    site.clock.advance(timedelta(minutes=5))

    closed = telegram.close(GROUP)

    assert (closed.status, closed.id, closed.group) == ("closed", opened.id, GROUP)
    assert closed.attended == 1
    assert closed.closed_at == site.clock.now()
    assert telegram.close(GROUP).status == "none"  # nothing open any more


def test_close_without_a_group_takes_the_latest_open_one(
    site: Site, telegram: TelegramAttendance
) -> None:
    telegram.open(TODAY, "first-group", 20)
    second = telegram.open(TODAY, "second-group", 20)

    closed = telegram.close(None)

    assert (closed.status, closed.id) == ("closed", second.id)


def test_the_report_has_counts_ratings_and_questions_and_no_addresses(
    site: Site, telegram: TelegramAttendance, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com", telegram=USER)
    person = participant_factory("two@example.com")
    code = str(site.open()["code"])
    telegram.open(TODAY, "other-group", 20)
    assert site.mark(code, person.email, rating="3", question="From the site").status_code == 200
    checkin_id = site.checkins()[0].id
    telegram.mark_code(code, USER.user_id)
    telegram.rate(checkin_id, USER.user_id, 5)
    telegram.ask(USER.user_id, "From Telegram")

    report = telegram.report(GROUP)

    assert report.status == "found" and report.id == checkin_id
    assert (report.attended, report.site, report.telegram) == (2, 1, 1)
    assert report.ratings == {1: 0, 2: 0, 3: 1, 4: 0, 5: 1}
    assert report.average == 4.0
    assert report.questions == ("From the site", "From Telegram")
    assert report.lesson_date == date.fromisoformat(LESSON) and report.group == GROUP
    assert "@" not in repr(report)


def test_the_report_of_a_group_is_of_its_latest_check_in_or_none(
    site: Site, telegram: TelegramAttendance
) -> None:
    assert telegram.report(None).status == "none"
    first = telegram.open(TODAY, GROUP, 20)
    site.clock.advance(timedelta(minutes=30))
    second = telegram.open(TODAY, GROUP, 20)
    telegram.open(TODAY, "other-group", 20)

    assert telegram.report(GROUP).id == second.id != first.id
    assert telegram.report("missing-group").status == "none"


# --- the marks --------------------------------------------------------------------------------


def test_a_mark_is_recorded_once_with_the_source_telegram(
    site: Site, telegram: TelegramAttendance, participant_factory: ParticipantFactory
) -> None:
    person = participant_factory("one@example.com", telegram=USER)
    opened = telegram.open(TODAY, GROUP, 20)

    first = telegram.mark_code(opened.code, USER.user_id)
    again = telegram.mark_code(opened.code, USER.user_id)

    assert (first.status, again.status) == ("marked", "already")
    assert first.lesson_date == TODAY
    [row] = site.attendance()
    assert (row.participant_id, row.source) == (person.id, "telegram")


def test_a_mark_on_the_site_is_not_marked_again_from_telegram(
    site: Site, telegram: TelegramAttendance, participant_factory: ParticipantFactory
) -> None:
    person = participant_factory("one@example.com", telegram=USER)
    code = str(site.open()["code"])
    assert site.mark(code, person.email).status_code == 200

    answer = telegram.mark_code(code.lower(), USER.user_id)

    assert answer.status == "already"
    assert [row.source for row in site.attendance()] == ["site"]


def test_a_mark_needs_a_linked_telegram_and_an_open_window(
    site: Site, telegram: TelegramAttendance, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com", telegram=USER)
    opened = telegram.open(TODAY, GROUP, 20)

    assert telegram.mark_code(opened.code, OTHER.user_id).status == "not_linked"
    assert telegram.mark_code("ZZZZ", OTHER.user_id).status == "not_linked"  # nothing about codes
    assert telegram.mark_code("ZZZZ", USER.user_id).status == "closed"
    site.clock.advance(timedelta(minutes=20))
    assert telegram.mark_code(opened.code, USER.user_id).status == "closed"
    assert site.attendance() == []


def test_the_window_is_closed_before_it_opens_too(
    site: Site, telegram: TelegramAttendance, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com", telegram=USER)
    opened = telegram.open(TODAY, GROUP, 20)
    site.clock.advance(timedelta(minutes=-1))

    assert telegram.mark_code(opened.code, USER.user_id).status == "closed"


# --- the rating -------------------------------------------------------------------------------


def test_a_rating_replaces_the_previous_one_until_a_day_after_closing(
    site: Site, telegram: TelegramAttendance, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com", telegram=USER)
    opened = telegram.open(TODAY, GROUP, 20)
    telegram.mark_code(opened.code, USER.user_id)

    assert telegram.rate(opened.id, USER.user_id, 4).status == "rated"
    assert telegram.rate(opened.id, USER.user_id, 2).status == "rated"
    assert [row.rating for row in site.attendance()] == [2]

    site.clock.advance(timedelta(hours=24, minutes=20) - timedelta(seconds=1))
    assert telegram.rate(opened.id, USER.user_id, 5).status == "rated"
    site.clock.advance(timedelta(seconds=1))
    assert telegram.rate(opened.id, USER.user_id, 1).status == "too_late"
    assert [row.rating for row in site.attendance()] == [5]


def test_a_closed_early_check_in_takes_ratings_a_day_from_the_closing(
    site: Site, telegram: TelegramAttendance, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com", telegram=USER)
    opened = telegram.open(TODAY, GROUP, 20)
    telegram.mark_code(opened.code, USER.user_id)
    site.clock.advance(timedelta(minutes=5))
    telegram.close(GROUP)

    site.clock.advance(timedelta(hours=23, minutes=59))
    assert telegram.rate(opened.id, USER.user_id, 3).status == "rated"
    site.clock.advance(timedelta(minutes=1))
    assert telegram.rate(opened.id, USER.user_id, 1).status == "too_late"


@pytest.mark.parametrize("rating", [0, 6, -1])
def test_a_rating_outside_one_to_five_is_not_stored(
    site: Site, telegram: TelegramAttendance, participant_factory: ParticipantFactory, rating: int
) -> None:
    participant_factory("one@example.com", telegram=USER)
    opened = telegram.open(TODAY, GROUP, 20)
    telegram.mark_code(opened.code, USER.user_id)

    assert telegram.rate(opened.id, USER.user_id, rating).status == "not_marked"
    assert [row.rating for row in site.attendance()] == [None]


def test_a_rating_needs_a_mark_of_the_person(
    site: Site, telegram: TelegramAttendance, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com", telegram=USER)
    opened = telegram.open(TODAY, GROUP, 20)

    assert telegram.rate(opened.id, USER.user_id, 4).status == "not_marked"
    assert telegram.rate(opened.id, OTHER.user_id, 4).status == "not_marked"
    assert telegram.rate(opened.id + 1000, USER.user_id, 4).status == "not_marked"
    assert site.attendance() == []


# --- the question -----------------------------------------------------------------------------


def test_questions_are_added_on_new_lines_up_to_the_limit(
    site: Site, telegram: TelegramAttendance, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com", telegram=USER)
    opened = telegram.open(TODAY, GROUP, 20)
    telegram.mark_code(opened.code, USER.user_id)

    assert telegram.ask(USER.user_id, "  First  ").status == "saved"
    assert telegram.ask(USER.user_id, "Second").status == "saved"
    assert [row.question for row in site.attendance()] == ["First\nSecond"]

    assert telegram.ask(USER.user_id, "x" * 500).status == "too_long"
    assert telegram.ask(USER.user_id, "x" * (500 - len("First\nSecond\n"))).status == "saved"
    assert [len(row.question or "") for row in site.attendance()] == [500]
    assert telegram.ask(USER.user_id, "y").status == "too_long"


def test_the_question_is_added_to_a_question_written_on_the_site(
    site: Site, telegram: TelegramAttendance, participant_factory: ParticipantFactory
) -> None:
    person = participant_factory("one@example.com", telegram=USER)
    code = str(site.open()["code"])
    site.mark(code, person.email, question="From the site")

    assert telegram.ask(USER.user_id, "From Telegram").status == "saved"

    assert [row.question for row in site.attendance()] == ["From the site\nFrom Telegram"]


def test_a_question_without_a_mark_or_a_registration_is_not_stored(
    site: Site, telegram: TelegramAttendance, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com", telegram=USER)
    telegram.open(TODAY, GROUP, 20)

    assert telegram.ask(USER.user_id, "No mark").status == "not_marked"
    assert telegram.ask(OTHER.user_id, "No registration").status == "not_marked"
    assert site.attendance() == []


def test_a_question_is_taken_until_a_day_after_the_window_closed(
    site: Site, telegram: TelegramAttendance, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com", telegram=USER)
    opened = telegram.open(TODAY, GROUP, 20)
    telegram.mark_code(opened.code, USER.user_id)
    site.clock.advance(timedelta(hours=24, minutes=20) - timedelta(seconds=1))
    assert telegram.ask(USER.user_id, "Just in time").status == "saved"

    site.clock.advance(timedelta(seconds=1))

    assert telegram.ask(USER.user_id, "Too late").status == "not_marked"
    assert [row.question for row in site.attendance()] == ["Just in time"]


def test_a_blank_question_is_not_stored(
    site: Site, telegram: TelegramAttendance, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com", telegram=USER)
    opened = telegram.open(TODAY, GROUP, 20)
    telegram.mark_code(opened.code, USER.user_id)

    assert telegram.ask(USER.user_id, "  \n ").status == "not_marked"
    assert [row.question for row in site.attendance()] == [None]


# --- storage failures -------------------------------------------------------------------------


def test_a_storage_failure_is_the_status_failed_and_nothing_is_raised(
    site: Site, telegram: TelegramAttendance, participant_factory: ParticipantFactory
) -> None:
    from sqlalchemy import text

    participant_factory("one@example.com", telegram=USER)

    with site.engine.begin() as connection:
        connection.execute(text("ALTER TABLE checkins RENAME TO checkins_gone"))
    try:
        results = [
            telegram.open(TODAY, GROUP, 20).status,
            telegram.close(None).status,
            telegram.report(None).status,
            telegram.mark_code("AB23", USER.user_id).status,
            telegram.rate(1, USER.user_id, 3).status,
            telegram.ask(USER.user_id, "Text").status,
            telegram.known_groups(8),
        ]
    finally:
        with site.engine.begin() as connection:
            connection.execute(text("ALTER TABLE checkins_gone RENAME TO checkins"))

    assert results == ["failed"] * 6 + [None]
