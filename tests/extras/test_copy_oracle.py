"""Text oracle of the counters (docs/copy.md, 1.9; requirements, section 16).

The oracle reads copy.md itself: the heading and both labels are verbatim, in order, on ``/`` in
each mode and in the fragment of ``/counters``; the labels sit next to their numbers.
"""

import pytest

from tests import copy_oracle as copy
from tests.extras.conftest import SiteFactory
from tests.html_tree import Node, parse

COUNTERS = copy.section("1.9")
TITLE = copy.one(COUNTERS, "Заголовок")
LABELS = copy.labeled(COUNTERS, "Підпис")
MODES = {"live": {}, "replay": {"SITE_MODE": "replay", "RECORDING_YOUTUBE_ID": "Rec0rding_ID"}}


def test_the_section_names_a_heading_and_two_labels() -> None:
    assert TITLE
    assert len(LABELS) == 2


def problems(section: Node) -> list[str]:
    """What the counters get wrong against copy.md 1.9."""
    found = []
    if section.find("h2").text() != TITLE:
        found.append("heading")
    items = section.find_all("p", class_="counters__item")
    labels = [item.find("span", class_="counters__label").text() for item in items]
    if labels != LABELS:
        found.append(f"labels {labels}")
    if [item for item in items if not item.find_all("span", class_="counters__number")]:
        found.append("a label without its number")
    return found


@pytest.mark.parametrize("mode", sorted(MODES))
def test_the_page_shows_the_texts(site_factory: SiteFactory, mode: str) -> None:
    site = site_factory(**MODES[mode])

    page = parse(site.client.get("/").text)

    assert problems(page.find("section", class_="counters")) == []


def test_the_fragment_shows_the_texts(site_factory: SiteFactory) -> None:
    site = site_factory()

    fragment = parse(site.client.get("/counters").text)

    assert problems(fragment.find("section", class_="counters")) == []


def test_the_oracle_catches_a_rewritten_label() -> None:
    made_up = parse(
        f'<section class="counters"><h2>{TITLE}</h2>'
        f'<p class="counters__item"><span class="counters__number">1</span>'
        f'<span class="counters__label">{LABELS[0]}</span></p>'
        f'<p class="counters__item"><span class="counters__number">1</span>'
        f'<span class="counters__label">у Telegram</span></p></section>'
    )

    assert problems(made_up.find("section")) == [f"labels [{LABELS[0]!r}, 'у Telegram']"]
