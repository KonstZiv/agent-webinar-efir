"""``GET`` and ``POST /checkin``: the mark on the lesson (docs/requirements.md, section 9а)."""

from datetime import timedelta

import pytest

from tests.checkin.conftest import Site
from tests.checkin.helpers import (
    CODE_INVALID,
    EMAIL_UNKNOWN,
    ERRORS,
    LESSON,
    SHOWN,
    page_texts,
)
from tests.conftest import ParticipantFactory
from tests.html_tree import parse

SUCCESS_LINE = SHOWN["success_text"].replace("{lesson_day_month}", "2 листопада")


def shown(response_text: str) -> str:
    return parse(response_text).find("div", id="checkin").text()


def test_the_page_without_javascript_has_the_form(site: Site) -> None:
    response = site.client.get("/checkin")

    assert response.status_code == 200
    page = parse(response.text)
    assert page.find("html")
    assert page.find("form", method="post").find("input", name="code")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-robots-tag"] == "noindex"
    assert page.find("meta", name="robots").attrs["content"] == "noindex"


def test_the_page_has_no_event_markup(site: Site) -> None:
    assert "application/ld+json" not in site.client.get("/checkin").text


def test_a_mark_is_recorded_once_with_the_source_site(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant = participant_factory("one@example.com")
    code = str(site.open()["code"])

    response = site.mark(code, "one@example.com")

    assert response.status_code == 200
    assert "<html" not in response.text
    text = shown(response.text)
    assert SHOWN["success_title"] in text
    assert SUCCESS_LINE.replace("{email}", "one@example.com") in text
    assert SHOWN["success_feedback"] not in text
    [row] = site.attendance()
    assert (row.participant_id, row.source, row.rating, row.question) == (
        participant.id,
        "site",
        None,
        None,
    )


def test_a_repeat_is_a_success_without_a_second_row(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com")
    code = str(site.open()["code"])

    first = site.mark(code, "one@example.com")
    second = site.mark(code, "one@example.com")

    assert first.status_code == second.status_code == 200
    assert len(site.attendance()) == 1


def test_the_code_and_the_address_may_be_written_loosely(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com")
    code = str(site.open()["code"])

    response = site.mark(f" {code.lower()} ", "  ONE@Example.com ")

    assert response.status_code == 200
    assert len(site.attendance()) == 1


def test_a_rating_and_a_question_are_kept_and_thanked(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com")
    code = str(site.open()["code"])

    response = site.mark(code, "one@example.com", rating="4", question="Коли запис?")

    assert SHOWN["success_feedback"] in shown(response.text)
    [row] = site.attendance()
    assert (row.rating, row.question) == (4, "Коли запис?")


def test_a_repeat_updates_what_is_passed_and_keeps_the_rest(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com")
    code = str(site.open()["code"])
    site.mark(code, "one@example.com", rating="3", question="Перше")

    site.mark(code, "one@example.com", rating="5")
    [row] = site.attendance()
    assert (row.rating, row.question) == (5, "Перше")

    site.mark(code, "one@example.com", question="Друге")
    site.mark(code, "one@example.com")
    [row] = site.attendance()
    assert (row.rating, row.question) == (5, "Друге")


def test_the_group_does_not_limit_who_may_mark(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant_factory("free@example.com")
    code = str(site.open(group="cbs-2026-10")["code"])

    assert site.mark(code, "free@example.com").status_code == 200


def test_the_success_names_the_date_of_the_checkin(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com")
    code = str(site.open(lesson_date="2026-12-09")["code"])

    text = shown(site.mark(code, "one@example.com").text)

    assert "9 грудня" in text


@pytest.mark.parametrize("closing", ["close", "expire"])
def test_a_closed_checkin_gives_the_error_of_the_code(
    site: Site, participant_factory: ParticipantFactory, closing: str
) -> None:
    participant_factory("one@example.com")
    opened = site.open()
    site.clock.advance(timedelta(minutes=1))
    if closing == "close":
        site.admin_post(f"/admin/checkins/{opened['id']}/close")
    else:
        site.clock.advance(timedelta(minutes=20))

    response = site.mark(str(opened["code"]), "one@example.com")

    assert response.status_code == 422
    assert CODE_INVALID in shown(response.text)
    assert site.attendance() == []


def test_the_window_opens_at_opened_at_and_closes_at_closes_at(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com")
    opened = site.open(window_minutes=5)
    code = str(opened["code"])

    site.clock.advance(timedelta(minutes=5) - timedelta(microseconds=1))
    assert site.mark(code, "one@example.com").status_code == 200
    site.clock.advance(timedelta(microseconds=1))
    assert site.mark(code, "one@example.com").status_code == 422


def test_an_unknown_code_is_the_same_error(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com")
    site.open()

    response = site.mark("ZZZZ", "one@example.com")

    assert response.status_code == 422
    assert CODE_INVALID in shown(response.text)


def test_an_unregistered_address_gets_its_error_with_a_link(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    code = str(site.open()["code"])

    response = site.mark(code, "stranger@example.com")

    assert response.status_code == 422
    assert EMAIL_UNKNOWN in shown(response.text)
    link = parse(response.text).find("a", href="/course")
    assert link.text() == "зареєструйтеся на сторінці курсу"
    assert site.attendance() == []


def test_the_code_is_checked_before_the_address(site: Site) -> None:
    """Without the code of an open check-in nobody learns who is registered."""
    response = site.mark("ZZZZ", "stranger@example.com")

    assert CODE_INVALID in shown(response.text)
    assert EMAIL_UNKNOWN not in shown(response.text)


@pytest.mark.parametrize(
    ("fields", "error"),
    [
        ({"code": "", "email": "one@example.com"}, "Код порожній"),
        ({"code": "ABCD", "email": ""}, "Поле пошти порожнє"),
        ({"code": "ABCD", "email": "not an address"}, "Адреса має неправильний формат"),
        (
            {"code": "ABCD", "email": "one@example.com", "question": "я" * 501},
            "Запитання довше за 500 знаків",
        ),
    ],
)
def test_the_form_errors(site: Site, fields: dict[str, str], error: str) -> None:
    response = site.client.post("/checkin", data=fields, headers={"HX-Request": "true"})

    assert response.status_code == 422
    assert ERRORS[error] in shown(response.text)


def test_a_question_of_500_characters_is_fine(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com")
    code = str(site.open()["code"])

    assert site.mark(code, "one@example.com", question="я" * 500).status_code == 200
    assert len(site.attendance()[0].question or "") == 500


def test_a_rating_outside_one_to_five_is_refused_and_writes_nothing(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com")
    code = str(site.open()["code"])

    for rating in ("0", "6", "x"):
        assert site.mark(code, "one@example.com", rating=rating).status_code == 422

    assert site.attendance() == []


def test_the_form_comes_back_with_what_was_typed(site: Site) -> None:
    response = site.mark("ZZZZ", "one@example.com", rating="4", question="Моє запитання")

    block = parse(response.text).find("div", id="checkin")
    assert block.find("input", name="code").attrs["value"] == "ZZZZ"
    assert block.find("input", name="email").attrs["value"] == "one@example.com"
    assert "checked" in block.find("input", name="rating", value="4").attrs
    assert "checked" not in block.find("input", name="rating", value="5").attrs
    assert "Моє запитання" in block.find("textarea").text()


def test_a_post_without_htmx_gets_the_page_with_the_same_block(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com")
    code = str(site.open()["code"])

    response = site.mark(code, "one@example.com", htmx=False)

    assert response.status_code == 200
    page = parse(response.text)
    assert page.find("html")
    line = SUCCESS_LINE.replace("{email}", "one@example.com")
    assert line in page.find("div", id="checkin").text()
    assert response.headers["vary"] == "HX-Request"


def test_the_eleventh_attempt_in_a_minute_is_429(site: Site) -> None:
    statuses = [site.mark("ZZZZ", "one@example.com").status_code for _ in range(11)]

    assert statuses == [422] * 10 + [429]
    response = site.mark("ZZZZ", "one@example.com")
    assert ERRORS["Забагато спроб поспіль"] in shown(response.text)


def test_the_limit_is_per_address_and_ends_with_the_minute(site: Site) -> None:
    for _ in range(10):
        site.mark("ZZZZ", "one@example.com")
    other = site.client.post(
        "/checkin",
        data={"code": "ZZZZ", "email": "one@example.com"},
        headers={"X-Real-IP": "203.0.113.9"},
    )
    assert other.status_code == 422

    site.clock.advance(timedelta(minutes=1, seconds=1))

    assert site.mark("ZZZZ", "one@example.com").status_code == 422


def test_get_does_not_count_as_an_attempt(site: Site) -> None:
    for _ in range(15):
        site.client.get("/checkin")

    assert site.mark("ZZZZ", "one@example.com").status_code == 422


def test_the_texts_are_found_in_the_copy() -> None:
    shown_texts, fields, errors = page_texts()

    assert shown_texts["title"] == "Відмітитись на занятті"
    assert len(fields) == 10 and len(errors) == 8
    assert LESSON == "2026-11-02"
