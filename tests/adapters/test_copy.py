"""Page texts are read from docs/copy.md and docs/materials.md at startup; a gap stops the app.

What the pages show is checked by the text oracle (tests/test_copy_oracle.py); here — that the
documents of the repository load, that a missing section or label is named, and that the values
``{event_…}`` are put in while an unknown value ``{…}`` stops the application.
"""

import re
import shutil
from datetime import date, datetime
from pathlib import Path

import pytest

from app.adapters.content.copy import load_page_texts
from app.adapters.content.legal import ContentError
from app.core.event_values import event_values
from tests.conftest import REPO_ROOT

DOCS = REPO_ROOT / "docs"
EVENT = event_values(datetime(2026, 10, 21, 19, 0), datetime(2026, 10, 21, 21, 0))


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    for name in ("copy.md", "materials.md"):
        shutil.copy(DOCS / name, tmp_path / name)
    return tmp_path


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_repository_documents_load() -> None:
    texts = load_page_texts(DOCS, event=EVENT)

    assert set(texts.first_screen) == {"live", "replay"}
    assert set(texts.service) == {"live", "replay"}
    assert texts.first_screen["live"].title == texts.first_screen["replay"].title
    assert texts.first_screen["live"].eyebrow != texts.first_screen["replay"].eyebrow
    assert texts.site_name and texts.image_alt and texts.materials_title
    assert texts.event.in_language == "uk"
    assert "<h1>" in texts.materials_html


@pytest.mark.parametrize(
    ("old", "new", "named"),
    [
        ("### 1.1. Перший екран", "### 1.11. Перший екран", "1.1"),
        ("## 10. Службові тексти сторінки", "## 12. Службові тексти сторінки", "10"),
        ("**replay**\n\n- Надзаголовок", "**повтор**\n\n- Надзаголовок", "replay"),
        ("- Під кнопкою: Після реєстрації —", "- Нижче: Після реєстрації —", "Під кнопкою"),
        ("| `og:site_name` |", "| `og:name` |", "og:site_name"),
        ("| Сторінка матеріалів |", "| Матеріали |", "Сторінка матеріалів"),
        ("### 1.7. Курс", "### 1.77. Курс", "1.7"),
        ("**live**\n\n1. Одразу", "**наживо**\n\n1. Одразу", "live"),
        ("- Вступ: Ведучий наживо", "- Початок: Ведучий наживо", "Вступ"),
        ("Подання: блок", "Вигляд: блок", "Подання"),
        ("«Вартість» видно завжди", "«Ціна» видно завжди", "Ціна"),
        ("пунктами (показується до 30.10.2026 включно):", "пунктами:", "Окремий рядок"),
        ("- Ім'я: Костянтин", "- Імʼя: Костянтин", "Ім'я"),
    ],
    ids=[
        "first-screen",
        "service-texts",
        "mode-group",
        "label",
        "shared-tag",
        "page-title",
        "course",
        "benefits-group",
        "on-air-label",
        "presentation",
        "always-visible-name",
        "likes-goal",
        "presenter-label",
    ],
)
def test_a_missing_piece_is_named(docs: Path, old: str, new: str, named: str) -> None:
    edit(docs / "copy.md", old, new)

    with pytest.raises(ContentError, match=named) as error:
        load_page_texts(docs, event=EVENT)

    assert "copy.md" in str(error.value)


def test_values_of_the_date_are_put_in() -> None:
    texts = load_page_texts(DOCS, event=EVENT)

    assert texts.first_screen["live"].when == "Середа, 21 жовтня 2026 року · 19:00–21:00 за Києвом"
    assert texts.first_screen["replay"].when == "Прямий ефір відбувся 21 жовтня 2026 року"
    assert texts.service["live"].title.endswith("«Архітектор замість кодера», 21 жовтня")
    assert "21 жовтня о 19:00 за Києвом" in texts.service["live"].description


@pytest.mark.parametrize(
    ("old", "new", "named"),
    [
        ("{event_date} · {event_start}", "{event_dat} · {event_start}", "{event_dat}"),
        ("- Коли: {event_weekday_capital}", "- Коли: {email} {event_weekday_capital}", "{email}"),
        ("- Вступ: Ведучий наживо", "- Вступ: {stream_url} Ведучий наживо", "{stream_url}"),
        ("| `og:title` |", "| `og:title` | {event_year}", "{event_year}"),
    ],
    ids=["misspelt", "a-slice-value", "landing-block", "service-tags"],
)
def test_an_unknown_value_stops_the_application(
    docs: Path, old: str, new: str, named: str
) -> None:
    edit(docs / "copy.md", old, new)

    with pytest.raises(ContentError, match=re.escape(named)) as error:
        load_page_texts(docs, event=EVENT)

    assert "copy.md" in str(error.value)


def test_without_the_event_the_values_stay_and_unknown_ones_still_stop(docs: Path) -> None:
    """The redirect stub has no ``EVENT_*`` and renders no page; a wrong value still stops it."""
    texts = load_page_texts(DOCS, event=None)

    assert "{event_date}" in texts.first_screen["replay"].when
    edit(docs / "copy.md", "{event_date} · {event_start}", "{event_dat} · {event_start}")
    with pytest.raises(ContentError, match=re.escape("{event_dat}")):
        load_page_texts(docs, event=None)


def test_missing_materials_document_is_named(docs: Path) -> None:
    (docs / "materials.md").unlink()

    with pytest.raises(ContentError, match="materials.md"):
        load_page_texts(docs, event=EVENT)


def test_raw_html_in_materials_is_escaped(docs: Path) -> None:
    edit(
        docs / "materials.md",
        "## 1. Що ви зберете і як читати",
        "## 1. Що ви зберете і як читати\n\n<script>alert(1)</script>",
    )

    assert "<script>" not in load_page_texts(docs, event=EVENT).materials_html


def test_landing_blocks_by_mode() -> None:
    """1.2 and 1.4 differ by mode; the rest of the blocks is the same in both."""
    texts = load_page_texts(DOCS, event=EVENT)
    live, replay = (texts.landing[mode].blocks for mode in ("live", "replay"))

    assert live.on_air.title != replay.on_air.title
    assert live.on_air.intro != replay.on_air.intro
    assert live.on_air.items == replay.on_air.items
    assert len(live.on_air.items) == 6
    assert live.benefits.title == replay.benefits.title
    assert live.benefits.items != replay.benefits.items
    assert len(live.benefits.items) == len(replay.benefits.items) == 3
    assert (live.audience, live.channel, live.presenter, live.course) == (
        replay.audience,
        replay.channel,
        replay.presenter,
        replay.course,
    )
    assert len(live.audience.items) == 3
    assert live.audience.subtitle and live.audience.text and live.audience.note


def test_inline_formatting_is_ready_html() -> None:
    blocks = load_page_texts(DOCS, event=EVENT).landing["live"].blocks

    assert blocks.on_air.items[0].startswith("<strong>")
    assert '<a href="https://t.me/agentic_engineers">' in blocks.on_air.items[2]
    assert blocks.channel.link.startswith('<a href="https://t.me/agentic_engineers">')
    assert blocks.channel.link.endswith("</a>")
    assert "**" not in blocks.presenter.text + blocks.course.intro


def test_course_accordion() -> None:
    course = load_page_texts(DOCS, event=EVENT).landing["live"].blocks.course
    by_title = {section.title: section for section in course.sections}

    # copy.md, 1.7 «Подання»: the intro, «Найближче заняття» and «Вартість» are always visible.
    assert [section.title for section in course.sections if section.always_visible] == [
        "Найближче заняття",
        "Вартість",
    ]
    assert len(course.sections) == 11
    program = by_title["Програма"]
    assert program.html == ""
    assert [block.html.count("<li>") for block in program.blocks] == [3, 3, 3, 2, 4]
    assert program.blocks[0].title.startswith("Блок I.")
    assert program.blocks[1].html.startswith('<ol start="4">')  # lessons keep their numbers
    assert [section.title for section in course.sections if section.blocks] == ["Програма"]
    assert '<div class="table-scroll"><table>' in by_title["Для кого курс"].html
    assert "<a href=" in by_title["Вартість"].html


def test_likes_goal_until_its_last_day() -> None:
    landing = load_page_texts(DOCS, event=EVENT).landing["replay"]

    assert landing.likes_goal_until == date(2026, 10, 30)
    assert landing.for_day(date(2026, 10, 30)) == landing.blocks
    assert landing.blocks.on_air.likes_goal
    after = landing.for_day(date(2026, 10, 31))
    assert after.on_air.likes_goal is None
    assert after.on_air.items == landing.blocks.on_air.items
    assert after.course == landing.blocks.course


def test_raw_html_in_a_block_is_escaped(docs: Path) -> None:
    edit(docs / "copy.md", "6. **Наприкінці** —", "6. **Наприкінці** <script>alert(1)</script> —")

    [*_, last] = load_page_texts(docs, event=EVENT).landing["live"].blocks.on_air.items

    assert "<script>" not in last
    assert "&lt;script&gt;" in last
