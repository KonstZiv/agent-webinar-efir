"""Two counters on the page that update themselves (docs/requirements.md, sections 8, 12, 15).

``_counters.html`` is included by ``/`` (the fallback page now, the landing later). On ``/`` it
shows «—» and asks htmx to load the numbers at once and every 15 seconds, so rendering ``/``
never touches the database. ``GET /counters`` answers with the same partial carrying the numbers
(polling every 15 seconds, without ``load``, or the swap would ask again at once); when the
database fails it answers 204, which htmx does not swap, so the page keeps what it shows. The
partial swaps in a 200 only. A slow database holds no request: while one poll reads, the others
answer at once from memory. «Зареєструвались» counts every participant, those of v1 too;
«підключили Telegram» — those with a linked Telegram. Numbers only: no address ever reaches the
page.
"""

from concurrent.futures import ThreadPoolExecutor, wait
from datetime import timedelta

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.adapters.extras.keys import REPORTS
from app.core.entities import TelegramAccount
from app.core.extras.ports import Counts
from app.main import create_app
from app.services import override
from tests.conftest import ParticipantFactory, SettingsFactory
from tests.extras.conftest import SiteFactory
from tests.extras.helpers import HOLD_LIMIT, RecordingStore, Site, SlowStore, failing, unavailable
from tests.fakes import FakeDatabaseProbe
from tests.html_tree import Node, parse
from tests.web.slice_partials import without_slice_partials

DASH = "—"
SWAP_ONLY_200 = "event.detail.shouldSwap = event.detail.xhr.status === 200"
THREAD_POOL = 40  # AnyIO's worker threads, shared by every sync route of the site
AT_ONCE = 5.0  # seconds: requests that do not wait for a read are answered far sooner


def counters_of(node: Node) -> Node:
    return node.find("section", class_="counters")


def numbers(section: Node) -> list[str]:
    return [span.text() for span in section.find_all("span", class_="counters__number")]


def home(client: TestClient) -> Node:
    response = client.get("/")
    assert response.status_code == 200
    return parse(response.text)


def fragment(site: Site) -> httpx.Response:
    return site.client.get("/counters", headers={"HX-Request": "true"})


# --- the page -----------------------------------------------------------------------------


def test_the_page_shows_the_counters_waiting_for_htmx(site: Site) -> None:
    section = counters_of(home(site.client))

    assert numbers(section) == [DASH, DASH]
    assert section.attrs["hx-get"] == "/counters"
    assert section.attrs["hx-trigger"] == "load, every 15s"
    assert section.attrs["hx-swap"] == "outerHTML"


def test_rendering_the_page_does_not_touch_the_database(site_factory: SiteFactory) -> None:
    store = RecordingStore()
    site = site_factory(overrides=[override(REPORTS, store)])

    home(site.client)

    assert store.calls == []


def test_the_page_works_without_any_database(make_settings: SettingsFactory) -> None:
    """The settings point to no server at all: the page and its counters render anyway."""
    app = create_app(make_settings(), db_probe=FakeDatabaseProbe())

    with TestClient(app) as client:
        section = counters_of(home(client))

    assert numbers(section) == [DASH, DASH]


def test_the_page_without_the_partial(make_settings: SettingsFactory) -> None:
    app = without_slice_partials(create_app(make_settings(), db_probe=FakeDatabaseProbe()))

    with TestClient(app) as client:
        page = home(client)

    assert page.find_all("section", class_="counters") == []


def drop_slice_global(app: FastAPI) -> FastAPI:
    """The partial is there, the slice is not installed (the foundation's sample slice tests)."""
    del app.state.container.templates.env.globals["counters"]
    return app


def test_the_partial_renders_nothing_without_its_slice(make_settings: SettingsFactory) -> None:
    app = drop_slice_global(create_app(make_settings(), db_probe=FakeDatabaseProbe()))

    with TestClient(app) as client:
        page = home(client)

    assert page.find_all("section", class_="counters") == []


def test_the_partial_brings_no_script(site: Site) -> None:
    """htmx comes once from base.html; the partial only sets attributes."""
    section = counters_of(home(site.client))

    assert section.find_all("script") == []


# --- GET /counters ------------------------------------------------------------------------


def test_the_fragment_carries_the_numbers(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant_factory(origin=None)  # v1
    participant_factory(telegram=TelegramAccount(1001, "first"))
    participant_factory(telegram=TelegramAccount(1002), channel_member=True)
    participant_factory()

    response = fragment(site)

    assert response.status_code == 200
    assert numbers(counters_of(parse(response.text))) == ["4", "2"]


def test_the_fragment_keeps_polling_without_load(site: Site) -> None:
    section = counters_of(parse(fragment(site).text))

    assert section.attrs["hx-get"] == "/counters"
    assert section.attrs["hx-trigger"] == "every 15s"
    assert section.attrs["hx-swap"] == "outerHTML"


def test_only_a_200_replaces_the_counters(site: Site) -> None:
    """The htmx config of base.html swaps in 422, 429 and 503, for the form. A 503 or 429 of a
    proxy in front of the site would replace the counters and end the polling."""
    on_the_page = counters_of(home(site.client))
    in_the_fragment = counters_of(parse(fragment(site).text))

    assert on_the_page.attrs["hx-on::before-swap"] == SWAP_ONLY_200
    assert in_the_fragment.attrs["hx-on::before-swap"] == SWAP_ONLY_200


def test_the_fragment_is_only_the_partial(site: Site) -> None:
    response = fragment(site)

    assert response.headers["content-type"].startswith("text/html")
    assert "<html" not in response.text
    assert response.text.strip().startswith("<section")


def test_an_empty_database_shows_zeros(site: Site) -> None:
    assert numbers(counters_of(parse(fragment(site).text))) == ["0", "0"]


def test_the_fragment_is_never_cached_or_indexed(site: Site) -> None:
    response = fragment(site)

    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-robots-tag"] == "noindex"


def test_numbers_are_read_once_per_15_seconds(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant_factory()
    assert numbers(counters_of(parse(fragment(site).text))) == ["1", "0"]
    participant_factory(telegram=TelegramAccount(2001))

    site.clock.advance(timedelta(seconds=14))
    assert numbers(counters_of(parse(fragment(site).text))) == ["1", "0"]
    site.clock.advance(timedelta(seconds=1))
    assert numbers(counters_of(parse(fragment(site).text))) == ["2", "1"]


def test_a_slow_read_holds_neither_the_page_nor_other_polls(site_factory: SiteFactory) -> None:
    """Polls waiting for one slow read would take the thread pool of every sync route, ``/``
    too (review r6, finding 1): more polls than threads, then the page, all while one read
    hangs. Each answers at once, the polls with the latest numbers."""
    store = SlowStore(counted=Counts(registered=128, telegram_linked=45))
    site = site_factory(overrides=[override(REPORTS, store)])
    assert numbers(counters_of(parse(fragment(site).text))) == ["128", "45"]
    store.counted = Counts(registered=129, telegram_linked=46)
    site.clock.advance(timedelta(seconds=15))
    store.held = True
    requests = ThreadPoolExecutor(max_workers=THREAD_POOL + 10)

    try:
        reader = requests.submit(fragment, site)
        assert store.reading.wait(HOLD_LIMIT)
        polls = [requests.submit(fragment, site) for _ in range(THREAD_POOL + 5)]
        _, waiting = wait(polls, timeout=AT_ONCE)
        assert waiting == set(), f"{len(waiting)} polls waited for the read"
        page = requests.submit(site.client.get, "/").result(timeout=AT_ONCE)
    finally:
        store.done.set()
        requests.shutdown()

    assert {tuple(numbers(counters_of(parse(poll.result().text)))) for poll in polls} == {
        ("128", "45")
    }
    assert page.status_code == 200
    assert numbers(counters_of(parse(reader.result().text))) == ["129", "46"]
    assert store.calls == ["counts", "counts"]


def test_a_database_failure_answers_204_and_htmx_keeps_the_numbers(
    site_factory: SiteFactory,
) -> None:
    site = site_factory(overrides=[override(REPORTS, unavailable())])

    response = fragment(site)

    assert response.status_code == 204
    assert response.content == b""
    assert response.headers["cache-control"] == "no-store"


def test_a_broken_statement_answers_204_too(site_factory: SiteFactory) -> None:
    site = site_factory(overrides=[override(REPORTS, failing())])

    assert fragment(site).status_code == 204


def test_the_fragment_answers_from_a_stand_in_store(site_factory: SiteFactory) -> None:
    store = RecordingStore(counted=Counts(registered=1234, telegram_linked=567))
    site = site_factory(overrides=[override(REPORTS, store)])

    assert numbers(counters_of(parse(fragment(site).text))) == ["1234", "567"]


def test_the_page_shows_numbers_only(site: Site, participant_factory: ParticipantFactory) -> None:
    """Hundreds watch the page live: no address of a participant ever reaches it."""
    created = [participant_factory(f"viewer-{n}@example.com") for n in range(3)]

    page = site.client.get("/").text
    shown = fragment(site).text + counters_of(parse(page)).text_raw()

    assert "@" not in shown
    assert [p.email for p in created if p.email in shown + page] == []
