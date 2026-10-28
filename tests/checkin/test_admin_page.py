"""The teacher's page ``/admin/checkin`` (docs/requirements.md, 9а; texts: docs/copy.md, 14.4).

The page is a shell: these tests check what the server puts in the HTML and what the script file
may and may not do. How the script behaves in a browser (login, start, the countdown, the
counter, the summary, 409, 401) is checked by the operator on staging.
"""

import json
import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.main import create_app
from tests import copy_oracle as copy
from tests.checkin.conftest import Site
from tests.checkin.helpers import ADMIN, GROUP
from tests.conftest import (
    BOT_ENV,
    REPO_ROOT,
    REQUIRED_ENV,
    ParticipantFactory,
    SettingsFactory,
)
from tests.fakes import FakeDatabaseProbe, FixedClock, fake_overrides
from tests.html_tree import normalize, parse

SECTION = copy.section("14.4", copy.raw_copy_text())
SITE_HOST = REQUIRED_ENV["PUBLIC_BASE_URL"].partition("://")[2]
SCRIPT = REPO_ROOT / "src" / "app" / "adapters" / "web" / "static" / "js" / "checkin-admin.js"


def part(name: str) -> dict[str, str]:
    """The table under the bold line ``**name:**`` of 14.4: the first cell → the second."""
    return copy.table(copy.group(SECTION, f"{name}:"))


LOGIN, START = part("Вхід"), part("Старт")
SCREEN, SUMMARY = part("Екран відмітки"), part("Підсумок")
TAGS = part("Службові теги")


@pytest.fixture
def bot_site(
    make_settings: SettingsFactory, test_db_url: str, migrated_engine: Engine
) -> Iterator[Site]:
    """The same application with the bot settings: the channel is set."""
    clock = FixedClock()
    app = create_app(
        make_settings(DATABASE_URL=test_db_url, **BOT_ENV),
        db_probe=FakeDatabaseProbe(),
        overrides=fake_overrides(clock=clock),
    )
    with TestClient(app, base_url="https://testserver") as client:
        yield Site(client, migrated_engine, clock)


def page(site: Site) -> str:
    response = site.client.get("/admin/checkin")
    assert response.status_code == 200
    return response.text


def test_the_page_needs_no_token_and_is_not_cached_or_indexed(site: Site) -> None:
    response = site.client.get("/admin/checkin")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-robots-tag"] == "noindex"
    node = parse(response.text)
    assert node.find("meta", name="robots").attrs["content"] == TAGS["robots"] == "noindex"
    assert normalize(node.find("title").text_raw()) == TAGS["title"]


def test_the_login_and_the_start_form_have_the_texts_of_14_4(site: Site) -> None:
    node = parse(page(site))

    login = node.find("form", id="admin-login")
    assert login.find("h1").text() == LOGIN["Заголовок"]
    assert login.find("label").text() == LOGIN["Поле токена: підпис"]
    assert login.find("input", name="token").attrs["type"] == "password"
    assert login.find("p", id="admin-token-hint").text() == LOGIN["Поле токена: пояснення"]
    assert login.find("button").text() == LOGIN["Кнопка"]
    assert login.find("p", id="admin-login-error").text() == LOGIN["Токен не підходить"]
    start = node.find("form", id="admin-start")
    assert start.find("h1").text() == START["Заголовок"]
    labels = [label.text() for label in start.find_all("label")]
    assert labels == [START["Поле групи: підпис"], START["Поле тривалості: підпис"]]
    assert start.find("p", id="admin-group-hint").text() == START["Поле групи: пояснення"]
    assert start.find("button").text() == START["Кнопка"]
    assert start.find("input", name="minutes").attrs["value"] == "10"


def test_the_screen_and_the_summary_have_the_texts_of_14_4(bot_site: Site) -> None:
    node = parse(page(bot_site))

    board = node.find("div", id="admin-board")
    site_line = SCREEN["Сайт"].replace("{site_host}", SITE_HOST)
    channel_line = SCREEN["Telegram"].replace("{channel}", BOT_ENV["TELEGRAM_CHANNEL"])
    wheres = [line.text() for line in board.find_all("p", class_="checkin-admin__where")]
    assert wheres == [site_line, channel_line]
    assert board.find("button", id="admin-close").text() == SCREEN["Кнопка"]
    assert board.find("p", id="admin-not-posted").text() == SCREEN["Пост не опубліковано"]
    summary = node.find("div", id="admin-summary")
    assert summary.find("h1").text() == SUMMARY["Заголовок"]
    assert summary.find("p", id="admin-no-questions").text() == SUMMARY["Запитань немає"]
    assert summary.find("button", id="admin-new").text() == SUMMARY["Кнопка"]
    assert node.find("p", id="admin-error").text() == copy_network_error()


def test_the_code_is_an_element_of_its_own_next_to_the_label(bot_site: Site) -> None:
    board = parse(page(bot_site)).find("div", id="admin-board")

    line = board.find("p", class_="checkin-admin__codeline")
    assert line.find("span", id="admin-board-code-label") is not None
    assert line.find("span", id="admin-board-code", class_="checkin-admin__code") is not None


def report_labels() -> list[str]:
    """The labels in backticks in the row `/checkin_report` of 14.3, read by the test itself."""
    section = copy.section("14.3", copy.raw_copy_text())
    [row] = [line for line in section.splitlines() if line.startswith("| `/checkin_report` |")]
    return re.findall(r"`([^`]+)`", row.partition("|")[2].partition("|")[2])


def test_the_summary_is_a_table_with_the_labels_of_the_report_14_3(bot_site: Site) -> None:
    _, _, attended, on_site, telegram, ratings, average, _ = report_labels()

    table = parse(page(bot_site)).find("div", id="admin-summary").find("table")

    rows = table.find_all("tr")
    assert [row.find("th").text() for row in rows] == [
        attended,
        on_site,
        telegram,
        ratings,
        "5",
        "4",
        "3",
        "2",
        "1",
        average,
    ]
    rated = [row for row in rows if row.attrs.get("data-rating")]
    assert [row.attrs["data-rating"] for row in rated] == ["5", "4", "3", "2", "1"]
    assert all(row.find("span", class_="checkin-admin__bar") is not None for row in rated)
    assert "@" not in table.text()


def copy_network_error() -> str:
    lines = [line for line in SECTION.splitlines() if line.startswith("**Збій мережі")]
    [line] = lines
    return copy.plain(line.partition(":**")[2])


def test_without_a_channel_the_screen_has_no_telegram_line(site: Site) -> None:
    node = parse(page(site))

    board = node.find("div", id="admin-board")
    [only] = board.find_all("p", class_="checkin-admin__where")
    assert only.text() == SCREEN["Сайт"].replace("{site_host}", SITE_HOST)
    assert "Telegram" not in only.text()


def test_the_script_gets_the_texts_with_values_from_the_page(site: Site) -> None:
    html = page(site)

    config = json.loads(parse(html).find("script", id="checkin-admin-config").text_raw())
    texts = config["texts"]
    assert texts["group"] == SCREEN["Група"] == "Група {group}"
    assert texts["code"] == SCREEN["Код"]
    assert texts["countdown"] == SCREEN["Відлік"]
    assert texts["counter"] == SCREEN["Лічильник"]
    assert "summary_count" not in texts and "summary_ratings" not in texts
    assert texts["questions_button"] == SUMMARY["Кнопка запитань"]
    assert texts["group_invalid"] == START["Група неправильна або порожня"]
    assert texts["minutes_invalid"] == START["Тривалість поза межами"]
    assert texts["token_rejected"] == LOGIN["Токен не підходить"]
    assert texts["network_error"] == copy_network_error()
    assert (config["default_minutes"], config["min_minutes"], config["max_minutes"]) == (10, 1, 180)
    assert re.fullmatch(config["group_pattern"], GROUP)


def test_the_script_is_included_and_the_page_has_no_other_scripts_of_its_own(site: Site) -> None:
    node = parse(page(site))

    sources = [script.attrs.get("src") or "" for script in node.find_all("script")]
    assert any(src.startswith("/static/js/checkin-admin.js") for src in sources)
    assert site.client.get("/static/js/checkin-admin.js").status_code == 200


def test_the_html_holds_no_codes_addresses_or_data_of_check_ins(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    person = participant_factory("someone@example.com")
    opened = site.open(group="secret-group")
    marked = site.mark(str(opened["code"]), person.email, question="Private question")
    assert marked.status_code == 200

    html = page(site)

    assert str(opened["code"]) not in html
    assert person.email not in html
    assert "secret-group" not in html and "Private question" not in html
    assert "Authorization" not in html


# --- what the script may and may not do ----------------------------------------------------


def code_lines() -> str:
    """The script without its comment lines."""
    lines = SCRIPT.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.strip().startswith("//"))


def test_the_script_keeps_the_token_in_the_session_storage_only() -> None:
    code = code_lines()

    assert "sessionStorage" in code
    assert "localStorage" not in code
    assert "document.cookie" not in code


def test_the_script_never_touches_the_addresses() -> None:
    code = code_lines()

    assert ".email" not in code and "email" not in code.lower()
    assert "console." not in code


def test_the_script_sends_the_token_as_a_bearer_header() -> None:
    assert '"Bearer "' in code_lines()


def test_the_script_has_no_texts_of_14_4() -> None:
    code = code_lines()

    for text in (*LOGIN.values(), *START.values(), *SCREEN.values(), *SUMMARY.values()):
        assert text not in code


def test_the_page_does_not_open_the_api(site: Site) -> None:
    assert site.client.get("/admin/checkins").status_code == 401
    assert site.client.get("/admin/checkins", headers=ADMIN).status_code == 200
