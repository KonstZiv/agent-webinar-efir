"""Text oracle of ``/stats`` (docs/copy.md, 12.2): verbatim, read from the file as the other
oracles do; the names of the levels come from docs/quiz.md (the results table)."""

from app.core.stats.ports import Group
from tests import copy_oracle as copy
from tests.html_tree import Node, parse
from tests.stats.conftest import Site, SiteFactory
from tests.stats.helpers import RecordingSource, quiz_levels, unavailable

STATS = copy.section("12.2")
TITLE = copy.one(STATS, "Заголовок")
REGISTRATIONS = copy.one(STATS, "Блок реєстрацій")
TOTAL = copy.one(STATS, "Усього")
CHART = copy.one(STATS, "Блок графіка")
CHART_CAPTION = copy.one(STATS, "Підпис графіка")
TELEGRAM = copy.one(STATS, "Блок Telegram")
SHARE = copy.one(STATS, "Частка Telegram")
SHARE_CAPTION = copy.one(STATS, "Підпис частки")
LEVELS = copy.one(STATS, "Блок рівнів")
NO_LEVEL = copy.one(STATS, "Без рівня")
FAILURE = copy.one(STATS, "Збій")


def test_the_section_names_every_text() -> None:
    assert "{telegram}" in SHARE_CAPTION
    assert "{total}" in SHARE_CAPTION
    assert list(quiz_levels()) == ["level1", "level1_plus", "level2"]


def problems(node: Node) -> list[str]:
    found = []
    if node.find("h1").text() != TITLE:
        found.append("title")
    article = node.find("article", class_="stats") if node.find_all("article") else node
    headings = [heading.text() for heading in article.find_all("h2")]
    if headings != [REGISTRATIONS, CHART, TELEGRAM, LEVELS]:
        found.append(f"headings {headings}")
    labels = [label.text() for label in node.find_all("span", class_="stats__label")]
    if labels != [TOTAL, SHARE]:
        found.append(f"labels {labels}")
    captions = [caption.text() for caption in node.find_all("p", class_="stats__caption")]
    if captions[0] != CHART_CAPTION:
        found.append(f"chart caption {captions[0]}")
    if node.find("title").text_raw() != TITLE:
        found.append("page title")
    return found


def test_the_page_shows_the_texts(site: Site) -> None:
    node = parse(site.client.get("/stats").text)

    assert problems(node) == []


def test_the_levels_are_named_as_in_the_quiz(site: Site) -> None:
    node = parse(site.client.get("/stats").text)

    names = [item.find("span", class_="stats__level-name").text() for item in
             node.find("ul", class_="stats__levels").find_all("li")]
    assert names == [*quiz_levels().values(), NO_LEVEL]


def test_the_caption_of_the_share_fills_the_numbers(site_factory: SiteFactory) -> None:
    from app.adapters.stats.keys import GROUPS
    from app.services import override

    source = RecordingSource(answer=[Group(None, True, None, 3), Group(None, False, None, 9)])
    site = site_factory(overrides=[override(GROUPS, source)])

    node = parse(site.client.get("/stats").text)

    caption = node.find("p", class_="stats__caption", id="telegram-caption").text()
    assert caption == SHARE_CAPTION.replace("{telegram}", "3").replace("{total}", "12")


def test_the_failure_message_is_verbatim(site_factory: SiteFactory) -> None:
    from app.adapters.stats.keys import GROUPS
    from app.services import override

    site = site_factory(overrides=[override(GROUPS, unavailable())])

    node = parse(site.client.get("/stats").text)

    assert node.find("p", class_="stats__failure").text() == FAILURE
    assert node.find("h1").text() == TITLE


def test_the_oracle_catches_a_rewritten_label() -> None:
    made_up = parse(
        f"<main><h1>{TITLE}</h1><h2>{REGISTRATIONS}</h2><h2>{CHART}</h2><h2>{TELEGRAM}</h2>"
        f"<h2>{LEVELS}</h2><span class='stats__label'>{TOTAL}</span>"
        f"<span class='stats__label'>Telegram</span>"
        f"<p class='stats__caption'>{CHART_CAPTION}</p><title>{TITLE}</title></main>"
    )

    assert problems(made_up) == [f"labels {[TOTAL, 'Telegram']}"]
