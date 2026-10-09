"""/privacy shows docs/legal/privacy.md as is."""

import re

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import SettingsFactory
from tests.fakes import FakeDatabaseProbe
from tests.html_tree import Node, normalize, parse
from tests.markdown_text import LEGAL_DIR, document_texts, plain

PRIVACY = (LEGAL_DIR / "privacy.md").read_text(encoding="utf-8")


def get_privacy(make_settings: SettingsFactory) -> Node:
    app = create_app(make_settings(), db_probe=FakeDatabaseProbe())
    with TestClient(app) as client:
        response = client.get("/privacy")
    assert response.status_code == 200
    return parse(response.text)


def test_privacy_headings_come_from_the_document(make_settings: SettingsFactory) -> None:
    page = get_privacy(make_settings)
    expected = [
        (len(m.group(1)), plain(m.group(2)))
        for m in re.finditer(r"^(#{1,3}) (.+)$", PRIVACY, flags=re.MULTILINE)
    ]

    main = page.find("main")
    rendered = [(int(n.tag[1]), n.text()) for n in main.iter() if re.fullmatch(r"h[1-3]", n.tag)]
    assert rendered == expected


def test_privacy_shows_the_whole_document(make_settings: SettingsFactory) -> None:
    text = get_privacy(make_settings).find("main").text()

    missing = [unit for unit in document_texts(PRIVACY) if unit not in text]
    assert missing == []


def test_privacy_title(make_settings: SettingsFactory) -> None:
    page = get_privacy(make_settings)
    first_heading = re.search(r"^# (.+)$", PRIVACY, flags=re.MULTILINE)
    assert first_heading is not None

    assert normalize(page.find("title").text_raw()) == plain(first_heading.group(1))


def test_privacy_tables_scroll_inside_wrapper(make_settings: SettingsFactory) -> None:
    page = get_privacy(make_settings)

    for table in page.find_all("table"):
        assert table.parent is not None
        assert table.parent.has("class", "table-scroll")
