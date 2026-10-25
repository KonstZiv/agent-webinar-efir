"""``GET /stats``: the live statistics, aggregates only (the issue «Statistic»).

Total registrations, the last 48 hours by hour in Kyiv time as an inline SVG, the share of
Telegram and the levels by their names from docs/quiz.md. The numbers are read once per
30 seconds; a database failure keeps the last known numbers or shows the message, and the page
stays up. Addresses are ``…@example.com`` only; none reaches the page.
"""

import re
from datetime import UTC, datetime, timedelta

from app.adapters.stats.keys import GROUPS
from app.core.entities import TelegramAccount
from app.core.stats.ports import Group
from app.services import override
from tests.conftest import REPO_ROOT, ParticipantFactory
from tests.fakes import WEBINAR_START, FixedClock
from tests.html_tree import Node, parse
from tests.stats.conftest import Site, SiteFactory
from tests.stats.helpers import RecordingSource, failing, quiz_levels, unavailable

NOW = WEBINAR_START  # 16:00 UTC, 19:00 in Kyiv: the first minute of the current hour


def page(site: Site) -> Node:
    response = site.client.get("/stats")
    assert response.status_code == 200
    return parse(response.text)


def numbers(node: Node) -> list[str]:
    return [span.text() for span in node.find_all("span", class_="stats__number")]


def bars(node: Node) -> list[int]:
    return [int(rect.attrs["data-count"] or "") for rect in node.find_all("rect")]


def levels(node: Node) -> list[tuple[str, str]]:
    items = node.find("ul", class_="stats__levels").find_all("li")
    return [
        (
            item.find("span", class_="stats__level-name").text(),
            item.find("span", class_="stats__number").text(),
        )
        for item in items
    ]


# --- the numbers --------------------------------------------------------------------------


def test_the_page_works_on_an_empty_database(site: Site) -> None:
    node = page(site)

    assert node.find("p", class_="stats__total").find("span", class_="stats__number").text() == "0"
    assert bars(node) == [0] * 48
    assert node.find_all("p", class_="stats__failure") == []


def test_the_aggregates_agree_with_the_participants(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    hour = timedelta(hours=1)
    participant_factory(registered_at=NOW, level="level1", telegram=TelegramAccount(1))
    participant_factory(registered_at=NOW + timedelta(minutes=20), level="level2")
    participant_factory(registered_at=NOW - hour, level="level2", telegram=TelegramAccount(2))
    participant_factory(registered_at=NOW - 3 * hour)
    participant_factory(registered_at=NOW - 100 * hour, level="level1")  # too old for the chart

    node = page(site)

    assert node.find("p", class_="stats__total").find("span", class_="stats__number").text() == "5"
    series = bars(node)
    assert (series[-1], series[-2], series[-4]) == (2, 1, 1)
    assert sum(series) == 4
    assert node.find("p", class_="stats__share").find("span", class_="stats__number").text() == (
        "40%"
    )
    assert node.find("p", class_="stats__caption", id="telegram-caption").text() == (
        "2 з 5 учасників."
    )
    names = quiz_levels()
    assert levels(node) == [
        (names["level1"], "2"),
        (names["level1_plus"], "0"),
        (names["level2"], "2"),
        ("Рівень не вказано", "1"),
    ]


def test_the_level_is_shown_by_its_name_never_by_its_code(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant_factory(level="level2")
    participant_factory(level="S1")  # a value the quiz does not name

    html = site.client.get("/stats").text

    assert "level2" not in html
    assert "level1" not in html
    assert "S1" not in html


def test_the_window_border_reaches_the_chart(
    site_factory: SiteFactory, participant_factory: ParticipantFactory
) -> None:
    site = site_factory()
    first = datetime(2026, 10, 19, 17, 0, tzinfo=UTC)  # the first bucket: 20:00 on 19.10 in Kyiv
    participant_factory(registered_at=first)
    participant_factory(registered_at=first - timedelta(seconds=1))

    series = bars(page(site))

    assert (series[0], sum(series)) == (1, 1)


def test_the_hour_that_repeats_gives_two_buckets(site_factory: SiteFactory) -> None:
    clock = FixedClock(datetime(2026, 10, 25, 12, 30, tzinfo=UTC))
    source = RecordingSource(
        answer=[
            Group(None, False, datetime(2026, 10, 25, 0, 0, tzinfo=UTC), 2),
            Group(None, False, datetime(2026, 10, 25, 1, 0, tzinfo=UTC), 5),
        ]
    )
    site = site_factory(clock=clock, overrides=[override(GROUPS, source)])

    node = page(site)

    series = bars(node)
    assert len(series) == 48
    assert [count for count in series if count] == [2, 5]
    labels = [rect.find("title").text_raw() for rect in node.find_all("rect")]
    assert sum(label.startswith("03:00") for label in labels) == 3  # the 24th, the 25th twice


# --- the chart ----------------------------------------------------------------------------


def test_the_chart_is_an_inline_svg_without_scripts(site: Site) -> None:
    node = page(site)

    svg = node.find("svg", class_="stats__chart")
    assert svg.attrs["role"] == "img"
    assert "viewbox" in svg.attrs  # the test parser lower-cases attribute names
    assert "width" not in svg.attrs
    assert "height" not in svg.attrs
    assert not [s for s in node.find_all("script") if "stats" in (s.attrs.get("src") or "")]


# --- privacy ------------------------------------------------------------------------------


def test_no_address_and_no_identifier_reaches_the_page(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory(
        "secret-person@example.com", telegram=TelegramAccount(7, "secret_username")
    )

    html = site.client.get("/stats").text

    assert "@" not in html
    assert "secret-person" not in html
    assert "secret_username" not in html
    assert str(created.unsubscribe_id) not in html


def test_the_page_is_never_indexed_or_cached_by_proxies(site: Site) -> None:
    response = site.client.get("/stats")

    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Robots-Tag"] == "noindex"


# --- the cache ----------------------------------------------------------------------------


def test_visitors_within_30_seconds_cost_one_read(site_factory: SiteFactory) -> None:
    source = RecordingSource()
    site = site_factory(overrides=[override(GROUPS, source)])

    for _ in range(5):
        assert site.client.get("/stats").status_code == 200
    site.clock.advance(timedelta(seconds=29))
    site.client.get("/stats")

    assert len(source.calls) == 1


def test_after_30_seconds_the_next_visitor_reads_again(site_factory: SiteFactory) -> None:
    source = RecordingSource()
    site = site_factory(overrides=[override(GROUPS, source)])
    site.client.get("/stats")

    site.clock.advance(timedelta(seconds=30))
    site.client.get("/stats")

    assert len(source.calls) == 2


def test_a_second_request_does_not_reach_the_database(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant_factory()
    first = page(site)
    participant_factory()

    second = page(site)

    assert numbers(first)[0] == numbers(second)[0] == "1"
    site.clock.advance(timedelta(seconds=30))
    assert numbers(page(site))[0] == "2"


# --- a database failure -------------------------------------------------------------------


def test_without_numbers_the_page_shows_the_message_and_stays_up(
    site_factory: SiteFactory,
) -> None:
    site = site_factory(overrides=[override(GROUPS, unavailable())])

    node = page(site)

    assert node.find("p", class_="stats__failure").text() == (
        "Статистика тимчасово недоступна. Оновіть сторінку за хвилину."
    )
    assert node.find_all("svg") == []


def test_a_broken_statement_keeps_the_page_up_too(site_factory: SiteFactory) -> None:
    site = site_factory(overrides=[override(GROUPS, failing())])

    assert site.client.get("/stats").status_code == 200


def test_the_last_known_numbers_stay_when_the_database_fails(site_factory: SiteFactory) -> None:
    source = RecordingSource(answer=[Group(None, True, None, 9)])
    site = site_factory(overrides=[override(GROUPS, source)])
    assert numbers(page(site))[0] == "9"

    source.error = unavailable().error
    site.clock.advance(timedelta(seconds=45))
    node = page(site)

    assert numbers(node)[0] == "9"
    assert node.find_all("p", class_="stats__failure") == []


# --- the layout at 375 px -----------------------------------------------------------------

CSS = (REPO_ROOT / "src" / "app" / "adapters" / "web" / "static" / "css" / "stats.css").read_text(
    encoding="utf-8"
)


def test_nothing_is_wider_than_a_375_px_screen() -> None:
    fixed = [int(px) for px in re.findall(r"(?<![-\w])(?:min-)?width:\s*(\d+)px", CSS)]

    assert all(width <= 300 for width in fixed)
    assert re.search(r"\.stats__chart\s*\{[^}]*width:\s*100%", CSS)
    assert re.search(r"\.stats__chart\s*\{[^}]*height:\s*auto", CSS)
    assert "overflow-x: scroll" not in CSS
