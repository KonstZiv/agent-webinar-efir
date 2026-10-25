"""Text oracle of the quiz block: docs/quiz.md and docs/copy.md 12.3, read by the test itself."""

from types import SimpleNamespace

from tests import copy_oracle as copy
from tests.html_tree import parse
from tests.quiz.conftest import Site
from tests.quiz.helpers import EMAIL, oracle

QUIZ = copy.section("12.3")


def block(site: Site) -> str:
    """The block as the success screen includes it."""
    env = site.client.app.state.container.templates.env  # type: ignore[attr-defined]
    return env.get_template("_quiz.html").render(
        registration_state=SimpleNamespace(email=EMAIL), site_mode="live"
    )  # type: ignore[no-any-return]


def test_the_block_shows_the_texts(site: Site) -> None:
    node = parse(block(site))
    questions, _ = oracle()

    assert node.find("h3", class_="quiz__title").text() == copy.one(QUIZ, "Заголовок")
    assert node.find("p", class_="quiz__intro").text() == copy.one(QUIZ, "Вступ")
    assert node.find("button").text() == copy.one(QUIZ, "Кнопка")
    legends = [legend.text() for legend in node.find_all("legend")]
    assert legends == [q.text for q in questions]
    options = [
        [label.text() for label in fieldset.find_all("label")]
        for fieldset in node.find_all("fieldset")
    ]
    assert options == [[text for text, _ in q.options] for q in questions]


def test_one_choice_per_question_and_no_points_in_the_markup(site: Site) -> None:
    node = parse(block(site))

    radios = node.find_all("input", type="radio")
    assert sorted({radio.attrs["name"] for radio in radios}) == ["q1", "q2", "q3", "q4", "q5"]
    assert {radio.attrs["value"] for radio in radios} == {"0", "1", "2"}
    assert len(radios) == 15


def test_the_form_carries_a_ticket(site: Site) -> None:
    node = parse(block(site))

    ticket = node.find("input", type="hidden")
    assert ticket.attrs["name"] == "ticket"
    assert ticket.attrs["value"] == site.ticket(EMAIL)


def test_the_block_is_absent_without_an_address(site: Site) -> None:
    env = site.client.app.state.container.templates.env  # type: ignore[attr-defined]

    assert env.get_template("_quiz.html").render().strip() == ""
