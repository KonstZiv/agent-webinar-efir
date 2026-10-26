"""The page ``/course`` (docs/copy.md, section 13): the form, the source and the success screen
are those of ``/``; the texts are checked by the oracle (tests/test_copy_oracle.py)."""

import pytest

from tests.course.conftest import Site, SiteFactory
from tests.html_tree import parse

UTM = "utm_source=google&utm_medium=cpc&utm_campaign=t&utm_content=c"
FORM_TITLE = "Зареєструватися на перше заняття"
MODES = {"live": {}, "replay": {"SITE_MODE": "replay", "RECORDING_YOUTUBE_ID": "dQw4w9WgXcQ"}}


@pytest.mark.parametrize("mode", sorted(MODES))
def test_the_page_opens_in_both_modes(site_factory: SiteFactory, mode: str) -> None:
    site = site_factory(**MODES[mode])

    response = site.client.get("/course")

    assert response.status_code == 200
    html = parse(response.text)
    assert html.find("h1", id="landing-hero-title").text() == "Агентна розробка на Python"
    assert html.find("section", id="register").find("h2").text() == FORM_TITLE
    assert '"@type": "Event"' not in response.text


def test_the_form_comes_right_after_the_first_screen(site: Site) -> None:
    html = parse(site.client.get("/course").text)
    sections = [node for node in html.find("main").iter() if node.tag == "section"]

    assert [node.attrs.get("id") or node.attrs.get("aria-labelledby") for node in sections][:2] == [
        "landing-hero-title",
        "register",
    ]


def test_the_source_of_the_page_reaches_the_participant(site: Site) -> None:
    site.client.get(f"/course?{UTM}")

    assert site.register().status_code == 200

    [participant] = site.participants()
    assert (
        participant.utm_source,
        participant.utm_medium,
        participant.utm_campaign,
        participant.utm_content,
    ) == ("google", "cpc", "t", "c")
    assert participant.landing_url == f"https://testserver/course?{UTM}"


@pytest.mark.parametrize("htmx", [True, False], ids=["htmx", "no-javascript"])
def test_the_success_screen_is_the_one_of_the_home_page(site: Site, htmx: bool) -> None:
    site.client.get(f"/course?{UTM}")

    response = site.register(htmx=htmx)

    assert response.status_code == 200
    assert [node for node in parse(response.text).iter() if "data-lead" in node.attrs]
    assert [participant.email for participant in site.participants()] == ["visitor@example.com"]


def register_title(text: str) -> str:
    return parse(text).find("section", id="register").find("h2").text()


def test_the_form_of_the_course_page_names_its_page(site: Site) -> None:
    html = parse(site.client.get("/course").text)

    form = html.find("section", id="register")
    [field] = [n for n in form.iter() if n.attrs.get("name") == "page"]
    assert field.attrs["value"] == "course"


def test_the_form_of_the_home_page_has_no_page_field(site: Site) -> None:
    html = parse(site.client.get("/").text)

    assert not [n for n in html.iter() if n.attrs.get("name") == "page"]


def test_a_refusal_through_htmx_keeps_the_texts_of_the_course_form(site: Site) -> None:
    response = site.refuse(page="course")

    assert response.status_code == 422
    assert register_title(response.text) == FORM_TITLE
    assert "email-error" in response.text


def test_a_refusal_without_htmx_is_the_course_page(site: Site) -> None:
    response = site.refuse(htmx=False, page="course")

    assert response.status_code == 422
    html = parse(response.text)
    assert html.find("h1", id="landing-hero-title").text() == "Агентна розробка на Python"
    assert register_title(response.text) == FORM_TITLE
    assert "email-error" in response.text


@pytest.mark.parametrize("extra", [{}, {"page": "foo"}, {"page": ""}])
def test_another_page_value_changes_nothing(site: Site, extra: dict[str, str]) -> None:
    response = site.refuse(**extra)

    assert response.status_code == 422
    assert register_title(response.text) != FORM_TITLE
