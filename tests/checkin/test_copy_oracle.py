"""Text oracle of ``/checkin``: docs/copy.md, section 14, read by the test itself."""

import re

from tests import copy_oracle as copy
from tests.checkin.conftest import Site
from tests.checkin.helpers import FIELDS, SHOWN
from tests.html_tree import normalize, parse

TAGS = copy.table(copy.section("14.2", copy.raw_copy_text()))
EDGES = re.findall(r"«([^»]+)»", FIELDS["Оцінка: варіанти"])


def test_the_page_shows_the_texts_of_section_14(site: Site) -> None:
    node = parse(site.client.get("/checkin").text)
    block = node.find("div", id="checkin")

    assert block.find("h1").text() == SHOWN["title"]
    assert block.find("p", class_="checkin__intro").text() == SHOWN["intro"]
    labels = [label.text() for label in block.find_all("label") if label.attrs.get("for")]
    assert labels == [
        FIELDS["Поле код: підпис"],
        FIELDS["Поле пошти: підпис"],
        FIELDS["Запитання: підпис"],
    ]
    assert block.find("legend").text() == FIELDS["Оцінка: підпис"]
    code_hint = block.find("input", name="code").attrs["placeholder"]
    email_hint = block.find("input", name="email").attrs["placeholder"]
    assert code_hint == FIELDS["Поле код: підказка в полі"]
    assert email_hint == FIELDS["Поле пошти: підказка в полі"]
    hint = block.find("p", class_="checkin__hint").text()
    assert hint == FIELDS["Поле пошти: пояснення під полем"]
    assert block.find("button").text() == FIELDS["Кнопка"]
    assert block.find("button").attrs["data-busy-label"] == FIELDS["Кнопка під час надсилання"]


def test_the_rating_is_five_choices_with_the_labels_of_the_edges(site: Site) -> None:
    block = parse(site.client.get("/checkin").text).find("div", id="checkin")

    radios = block.find_all("input", type="radio")
    assert [radio.attrs["value"] for radio in radios] == ["1", "2", "3", "4", "5"]
    assert {radio.attrs["name"] for radio in radios} == {"rating"}
    edges = block.find("p", class_="checkin__edges").find_all("span")
    assert [span.text() for span in edges] == EDGES
    assert EDGES == ["1 — слабко", "5 — чудово"]


def test_the_question_field_is_labelled_with_its_limit(site: Site) -> None:
    block = parse(site.client.get("/checkin").text).find("div", id="checkin")

    assert "500" in block.find("label", **{"for": "checkin-question"}).text()


def test_the_service_tags_come_from_section_14_2(site: Site) -> None:
    node = parse(site.client.get("/checkin").text)

    assert normalize(node.find("title").text_raw()) == TAGS["title"]
    assert node.find("meta", name="description").attrs["content"] == TAGS["description"]
    assert node.find("meta", name="robots").attrs["content"] == TAGS["robots"] == "noindex"


def test_no_value_in_braces_reaches_the_page(site: Site) -> None:
    text = site.client.get("/checkin").text

    assert "{lesson_" not in text and "{email}" not in text
