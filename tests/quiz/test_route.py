"""``POST /quiz``: the fragment of the result, the ticket, nothing written on a bad answer."""

import dataclasses
from datetime import timedelta

import pytest

from app.core.quiz.ticket import TERM
from tests import copy_oracle as copy
from tests.html_tree import parse
from tests.quiz.conftest import Site
from tests.quiz.helpers import EMAIL, HTMX, answers_for, oracle

INCOMPLETE = copy.one(copy.section("12.3"), "Неповна відповідь")
NOT_SAVED = copy.one(copy.section("12.3"), "Збій збереження")
EXPIRED = copy.one(copy.section("12.3"), "Час минув")
ALL_ZERO = answers_for([0] * 5)
ALL_TWO = answers_for([2] * 5)


def post(site: Site, fields: dict[str, str], *, ticket: str | None = None, htmx: bool = True):  # type: ignore[no-untyped-def]
    data = {"ticket": site.ticket(EMAIL) if ticket is None else ticket, **fields}
    return site.client.post("/quiz", data=data, headers=HTMX if htmx else {})


def test_the_answer_is_a_fragment_that_replaces_the_form(site: Site) -> None:
    response = post(site, ALL_TWO)

    assert response.status_code == 200
    assert "<html" not in response.text
    node = parse(response.text)
    assert node.find("div", id="quiz").find("div", id="quiz-result")
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(("fields", "level"), [(ALL_ZERO, "level1"), (ALL_TWO, "level2")])
def test_the_result_shows_the_name_and_advice_and_stores_the_level(
    site: Site, fields: dict[str, str], level: str
) -> None:
    expected = next(r for r in oracle()[1] if r.level == level)

    text = parse(post(site, fields).text).find("div", id="quiz-result").text()

    assert expected.name in text
    assert expected.advice in text
    assert site.store.levels == {EMAIL: level}


def test_no_points_are_shown(site: Site) -> None:
    text = parse(post(site, ALL_TWO).text).text()

    assert "балів" not in text
    assert "10" not in text


def test_a_second_pass_overwrites_the_level(site: Site) -> None:
    post(site, ALL_TWO)
    post(site, ALL_ZERO)

    assert site.store.levels == {EMAIL: "level1"}


def test_the_answer_without_javascript_is_a_page_with_the_anchor(site: Site) -> None:
    response = post(site, ALL_TWO, htmx=False)

    page = parse(response.text)
    assert response.status_code == 200
    assert page.find("div", id="quiz-result").text()
    assert "noindex" in response.text


def test_the_form_leads_to_the_anchor_of_the_result_not_of_the_registration(site: Site) -> None:
    incomplete = post(site, {"q1": "0"})

    form = parse(incomplete.text).find("form", class_="quiz__form")
    assert form.attrs["action"] == "/quiz#quiz-result"
    assert form.attrs["hx-target"] == "#quiz"
    assert "#register" not in incomplete.text


@pytest.mark.parametrize(
    "fields",
    [{}, {"q1": "0"}, {**ALL_TWO, "q3": ""}, {**ALL_TWO, "q3": "9"}, {**ALL_TWO, "q3": "x"},
     {**ALL_TWO, "q3": "-1"}],
)
def test_an_incomplete_or_spoiled_answer_gives_the_message_and_writes_nothing(
    site: Site, fields: dict[str, str]
) -> None:
    response = post(site, fields)

    assert response.status_code == 422
    assert parse(response.text).find("p", class_="quiz__error").text() == INCOMPLETE
    assert site.store.writes == []


def test_the_chosen_options_stay_in_the_form_after_a_problem(site: Site) -> None:
    node = parse(post(site, {"q1": "2", "q2": "1"}).text)

    checked = {
        radio.attrs["name"]: radio.attrs["value"]
        for radio in node.find_all("input", type="radio")
        if "checked" in radio.attrs
    }
    assert checked == {"q1": "2", "q2": "1"}


def test_a_failed_storage_gives_the_message_and_keeps_the_form(site: Site) -> None:
    site.store.broken = True

    response = post(site, ALL_TWO)

    assert response.status_code == 503
    node = parse(response.text)
    assert node.find("p", class_="quiz__error").text() == NOT_SAVED
    assert node.find("form")


@pytest.mark.parametrize("ticket", ["", "forged", "a.b", "x" * 300])
def test_a_forged_ticket_is_refused_and_writes_nothing(site: Site, ticket: str) -> None:
    response = post(site, ALL_TWO, ticket=ticket)

    assert response.status_code == 422
    assert parse(response.text).find("p", class_="quiz__error").text() == EXPIRED
    assert site.store.writes == []


def test_a_ticket_with_a_non_ascii_signature_is_refused_not_a_server_error(site: Site) -> None:
    payload = site.ticket(EMAIL).partition(".")[0]

    response = post(site, ALL_TWO, ticket=f"{payload}.é")

    assert response.status_code == 422
    assert parse(response.text).find("p", class_="quiz__error").text() == EXPIRED
    assert site.store.writes == []


def test_a_ticket_cannot_be_turned_to_another_address(site: Site) -> None:
    site.store.known.add("other@example.com")
    payload, _, signature = site.ticket(EMAIL).partition(".")
    other = site.ticket("other@example.com").partition(".")[0]

    response = post(site, ALL_TWO, ticket=f"{other}.{signature}")

    assert response.status_code == 422
    assert payload != other
    assert site.store.writes == []


def test_an_expired_ticket_is_refused(site: Site) -> None:
    ticket = site.ticket(EMAIL)
    site.clock.advance(TERM + timedelta(seconds=1))

    response = post(site, ALL_TWO, ticket=ticket)

    assert response.status_code == 422
    assert parse(response.text).find("p", class_="quiz__error").text() == EXPIRED
    assert site.store.writes == []


def test_a_removed_participant_gets_the_expired_message(site: Site) -> None:
    site.store.known.clear()

    response = post(site, ALL_TWO)

    assert parse(response.text).find("p", class_="quiz__error").text() == EXPIRED


def test_the_response_carries_no_ticket_or_address(site: Site) -> None:
    text = post(site, ALL_TWO).text

    assert EMAIL not in text
    assert site.ticket(EMAIL) not in text


def test_only_the_level_is_stored_never_the_points(site: Site) -> None:
    post(site, ALL_TWO)

    assert dataclasses.is_dataclass(site.store)
    assert site.store.writes == [(EMAIL, "level2")]
