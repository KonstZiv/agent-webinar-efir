"""Legal texts are read from docs/ at startup; a missing file or section stops the app.

Rendering rules are checked on small documents written by the tests, so a project that
replaces the sample texts in docs/legal keeps these tests; the real documents only have to
load (``test_repository_documents_load``).
"""

import re
from pathlib import Path

import pytest

from app.adapters.content.legal import ContentError, LegalTexts, load_legal_texts
from tests.conftest import REPO_ROOT
from tests.markdown_text import plain

PRIVACY = """\
# Політика приватності

**Версія 1.**

## 1. Хто відповідає

Пишіть на privacy@example.com.

## 2. Сервіси

| Сервіс | Політика |
| :-- | :-- |
| Railway | https://railway.com/legal/privacy |

Як Google використовує дані: https://policies.google.com/technologies/partner-sites.
Докладніше — [політика Google](https://policies.google.com/privacy).
"""

CONSENT = """\
# Текст згоди

## Текст позначки

Я погоджуюся з обробкою даних; докладніше — в [політиці приватності](/privacy).

## Як використовувати

- Позначка одна.
"""

BANNER = """\
# Банер

## Текст банера

**Заголовок:** Файли cookie й аналітика

**Текст:** Ми хочемо використовувати аналітику. Докладніше — в [політиці приватності](/privacy).

**Кнопки:** «Дозволити» · «Відхилити»

**Посилання внизу кожної сторінки:** «Налаштування cookie» — відкриває банер повторно.

## Примітка

Інше.
"""


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    legal = tmp_path / "legal"
    legal.mkdir()
    (legal / "privacy.md").write_text(PRIVACY, encoding="utf-8")
    (legal / "consent.md").write_text(CONSENT, encoding="utf-8")
    (legal / "cookie-banner.md").write_text(BANNER, encoding="utf-8")
    return tmp_path


@pytest.fixture
def legal(docs: Path) -> LegalTexts:
    return load_legal_texts(docs)


def test_repository_documents_load() -> None:
    texts = load_legal_texts(REPO_ROOT / "docs")
    source = (REPO_ROOT / "docs" / "legal" / "privacy.md").read_text(encoding="utf-8")

    assert texts.privacy_title == plain(re.findall(r"^# (.+)$", source, flags=re.MULTILINE)[0])


def test_privacy_document(legal: LegalTexts) -> None:
    assert legal.privacy_title == "Політика приватності"
    for heading in ("1. Хто відповідає", "2. Сервіси"):
        assert f"<h2>{heading}</h2>" in legal.privacy_html
    assert legal.privacy_html.count('<div class="table-scroll"><table>') == 1
    assert legal.privacy_html.count("</table></div>") == 1


@pytest.mark.parametrize(
    ("heading", "title"),
    [
        ("# Політика **приватності** `v2`", "Політика приватності v2"),
        ("# [Політика](/privacy) *приватності*", "Політика приватності"),
    ],
)
def test_privacy_title_is_the_visible_heading_text(docs: Path, heading: str, title: str) -> None:
    """The title goes to <title> and the footer link: no Markdown markup in it."""
    path = docs / "legal" / "privacy.md"
    path.write_text(PRIVACY.replace("# Політика приватності", heading, 1), encoding="utf-8")

    assert load_legal_texts(docs).privacy_title == title


def test_consent_text(legal: LegalTexts) -> None:
    assert legal.consent_html.startswith("Я погоджуюся")
    assert '<a href="/privacy">політиці приватності</a>' in legal.consent_html
    assert "Позначка одна" not in legal.consent_html


def test_cookie_banner(legal: LegalTexts) -> None:
    banner = legal.banner

    assert banner.title == "Файли cookie й аналітика"
    assert banner.text_html.startswith("Ми хочемо використовувати аналітику")
    assert '<a href="/privacy">політиці приватності</a>' in banner.text_html
    assert (banner.allow, banner.reject) == ("Дозволити", "Відхилити")
    assert banner.settings_link == "Налаштування cookie"


def test_raw_html_in_docs_is_escaped(docs: Path) -> None:
    consent = docs / "legal" / "consent.md"
    consent.write_text(
        CONSENT.replace("Я погоджуюся", "<script>alert(1)</script> Я погоджуюся"),
        encoding="utf-8",
    )

    assert "<script>" not in load_legal_texts(docs).consent_html


@pytest.mark.parametrize("name", ["privacy.md", "consent.md", "cookie-banner.md"])
def test_missing_file_is_named(docs: Path, name: str) -> None:
    (docs / "legal" / name).unlink()

    with pytest.raises(ContentError, match=name):
        load_legal_texts(docs)


@pytest.mark.parametrize(
    ("name", "marker", "expected"),
    [
        ("privacy.md", "# Політика приватності", "top heading"),
        ("consent.md", "## Текст позначки", "Текст позначки"),
        ("cookie-banner.md", "## Текст банера", "Текст банера"),
        ("cookie-banner.md", "**Кнопки:**", "Кнопки"),
        ("cookie-banner.md", "**Заголовок:**", "Заголовок"),
        ("cookie-banner.md", "**Посилання внизу кожної сторінки:**", "Посилання"),
    ],
)
def test_missing_section_is_named(docs: Path, name: str, marker: str, expected: str) -> None:
    path = docs / "legal" / name
    path.write_text(path.read_text(encoding="utf-8").replace(marker, "Інше"), encoding="utf-8")

    with pytest.raises(ContentError, match=expected):
        load_legal_texts(docs)


# --- bare addresses in the policy are links ------------------------------------------------


def test_bare_urls_and_emails_become_links(legal: LegalTexts) -> None:
    html = legal.privacy_html

    assert (
        '<a href="https://railway.com/legal/privacy">https://railway.com/legal/privacy</a>' in html
    )
    assert '<a href="mailto:privacy@example.com">privacy@example.com</a>' in html
    # Trailing sentence punctuation stays outside the link.
    assert "partner-sites</a>." in html
    assert not re.search(r"<a [^>]*>[^<]*<a ", html)  # no nested links


def test_existing_markdown_links_are_not_doubled(legal: LegalTexts) -> None:
    assert '<a href="https://policies.google.com/privacy">політика Google</a>' in (
        legal.privacy_html
    )
    assert '<a href="<a' not in legal.privacy_html


# --- an empty banner title or text stops the app -------------------------------------------


@pytest.mark.parametrize("label", ["**Заголовок:**", "**Текст:**"])
def test_empty_banner_value_is_rejected(docs: Path, label: str) -> None:
    path = docs / "legal" / "cookie-banner.md"
    lines = [
        label if line.startswith(label) else line
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ContentError, match=label.strip("*").rstrip(":")):
        load_legal_texts(docs)


def test_banner_needs_two_buttons(docs: Path) -> None:
    path = docs / "legal" / "cookie-banner.md"
    path.write_text(
        BANNER.replace("«Дозволити» · «Відхилити»", "«Дозволити»"), encoding="utf-8"
    )

    with pytest.raises(ContentError, match="two buttons"):
        load_legal_texts(docs)


# --- reading: BOM, undecodable bytes, a directory in place of a file -----------------------


@pytest.mark.parametrize("name", ["privacy.md", "consent.md", "cookie-banner.md"])
def test_byte_order_mark_is_accepted(docs: Path, name: str) -> None:
    path = docs / "legal" / name
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())

    texts = load_legal_texts(docs)

    assert texts.privacy_title == "Політика приватності"
    assert texts.banner.title == "Файли cookie й аналітика"


def test_undecodable_file_is_named(docs: Path) -> None:
    (docs / "legal" / "consent.md").write_bytes(b"\xff\xfe broken")

    with pytest.raises(ContentError, match="consent.md"):
        load_legal_texts(docs)


def test_unreadable_path_is_named(docs: Path) -> None:
    path = docs / "legal" / "privacy.md"
    path.unlink()
    path.mkdir()

    with pytest.raises(ContentError, match="privacy.md"):
        load_legal_texts(docs)


# --- every table gets exactly one scroll wrapper -------------------------------------------


def test_each_table_is_wrapped_once(docs: Path) -> None:
    path = docs / "legal" / "privacy.md"
    extra = "\n\n| A | B |\n| :-- | :-- |\n| `<table>` | x |\n"
    path.write_text(PRIVACY + extra, encoding="utf-8")

    html = load_legal_texts(docs).privacy_html

    assert html.count('<div class="table-scroll"><table>') == html.count("<table>") == 2
    assert html.count("</table></div>") == html.count("</table>") == 2
    assert "&lt;table&gt;" in html
