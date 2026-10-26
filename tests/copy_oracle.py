"""Test oracle for page texts: reads docs/copy.md line by line, independently of the application.

Pages must contain these texts verbatim (Markdown markup removed, whitespace collapsed). The
foundation checks ``/`` and the materials page (tests/test_copy_oracle.py); each slice checks
its own pages and partials with the same helpers:

    form = copy.group(copy.section("1.8"), "live")
    assert copy.one(form, "Заголовок") in page_text

Blocks 1.2–1.7 of the landing: ``block_texts(number, mode)`` — every text unit the page shows
in the mode; ``likes_goal()`` — the line about the likes and its last day.

The date of the webinar is not written in copy.md: it stands there as values ``{event_…}``
(section 11), which the site fills from ``EVENT_START`` and ``EVENT_END``. The oracle formats
them itself, never through the site's code: ``copy_text()`` is copy.md with the values of the
test application (``REQUIRED_ENV`` of tests/conftest.py) put in; a test with other settings
passes their ``start`` and ``end``:

    text = copy.copy_text(settings.event_start, settings.event_end)
    when = copy.one(copy.group(copy.section("1.1", text), "live"), "Коли")
"""

import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tests.conftest import REQUIRED_ENV

ROOT = Path(__file__).resolve().parents[1]
COPY_FILE = ROOT / "docs" / "copy.md"
MATERIALS_FILE = ROOT / "docs" / "materials.md"

# The oracle's own names for the values of the webinar's date (copy.md, section 11).
WEEKDAYS = ("понеділок", "вівторок", "середа", "четвер", "п'ятниця", "субота", "неділя")
MONTHS = (
    "січня",
    "лютого",
    "березня",
    "квітня",
    "травня",
    "червня",
    "липня",
    "серпня",
    "вересня",
    "жовтня",
    "листопада",
    "грудня",
)
# Sections where the values of the webinar's date stand; 11 lists them.
EVENT_SECTIONS = frozenset({"1.1", "5", "6.1", "10", "11"})
# EVENT_START and EVENT_END of the test application: naive Kyiv wall time, as the site reads it.
EVENT_START = datetime.fromisoformat(REQUIRED_ENV["EVENT_START"])
EVENT_END = datetime.fromisoformat(REQUIRED_ENV["EVENT_END"])

MODES = ("live", "replay")
# Labels of blocks 1.2–1.7 whose values the page shows; the label itself is not shown.
LABELS = (
    "Заголовок",
    "Вступ",
    "Підзаголовок",
    "Примітка під текстом",
    "Текст",
    "Посилання",
    "Ім'я",
)
# Notes on how a block is presented, not page texts.
NOTES = ("Подання:", "Пункти (обидва режими):")

_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_HEADING = re.compile(r"^(#{2,3}) (\d+(?:\.\d+)?)\. ")
_BOLD_START = re.compile(r"^\*\*(.+?)\*\*")
_KYIV_MOMENT = re.compile(r"(\d{2})\.(\d{2})\.(\d{4}), (\d{2}):(\d{2}), пояс (\S+)")
_LIST_ITEM = re.compile(r"^(?:- |\d+\. )(.+)$")
_TABLE_RULE = re.compile(r"^\|[\s:|-]+\|$")
_LIKES_GOAL = re.compile(
    r"^Окремий рядок під пунктами \(показується до (\d{2})\.(\d{2})\.(\d{4}) включно\): (.+)$"
)
_EVENT_VALUE = re.compile(r"\{(event_[a-z_]+)\}")
_VALUE_NAME = re.compile(r"\{([a-z_]+)\}")


def plain(markdown: str) -> str:
    """Remove inline Markdown (links, bold, italic, code) and collapse whitespace.

    >>> plain("**Bold** text with [a link](/privacy) and `code`")
    'Bold text with a link and code'
    """
    text = _LINK.sub(r"\1", markdown)
    text = text.replace("**", "").replace("`", "")
    text = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"\1", text)
    return " ".join(text.split())


def raw_copy_text() -> str:
    """docs/copy.md as written: the values ``{…}`` not put in."""
    return COPY_FILE.read_text(encoding="utf-8")


def event_values(start: datetime, end: datetime) -> dict[str, str]:
    """The values ``{event_…}`` of copy.md, section 11, for naive Kyiv wall times.

    >>> values = event_values(datetime(2026, 10, 21, 19, 0), datetime(2026, 10, 21, 21, 0))
    >>> values["event_weekday"], values["event_weekday_capital"], values["event_date"]
    ('середа', 'Середа', '21 жовтня 2026 року')
    >>> values["event_day_month"], values["event_start"], values["event_end"]
    ('21 жовтня', '19:00', '21:00')
    >>> values["event_start_moment"], values["event_end_moment"]
    ('2026-10-21T19:00+03:00', '2026-10-21T21:00+03:00')
    """
    kyiv = ZoneInfo("Europe/Kyiv")
    weekday = WEEKDAYS[start.weekday()]
    day_month = f"{start.day} {MONTHS[start.month - 1]}"
    return {
        "event_weekday": weekday,
        "event_weekday_capital": weekday[0].upper() + weekday[1:],
        "event_date": f"{day_month} {start.year} року",
        "event_day_month": day_month,
        "event_start": f"{start:%H:%M}",
        "event_end": f"{end:%H:%M}",
        "event_start_moment": start.replace(tzinfo=kyiv).isoformat(timespec="minutes"),
        "event_end_moment": end.replace(tzinfo=kyiv).isoformat(timespec="minutes"),
    }


def lesson_values(start: datetime) -> dict[str, str]:
    """The values ``{lesson_…}`` of copy.md, section 11, for a naive Kyiv wall time.

    >>> lesson_values(datetime(2026, 10, 28, 19, 0))
    {'lesson_weekday': 'середа', 'lesson_date': '28 жовтня 2026 року', 'lesson_start': '19:00'}
    """
    return {
        "lesson_weekday": WEEKDAYS[start.weekday()],
        "lesson_date": f"{start.day} {MONTHS[start.month - 1]} {start.year} року",
        "lesson_start": f"{start:%H:%M}",
    }


def course_text(lesson_start: datetime) -> str:
    """docs/copy.md with the values of the webinar and of the nearest lesson put in."""
    text = copy_text()
    for name, value in lesson_values(lesson_start).items():
        text = text.replace(f"{{{name}}}", value)
    return text


def fill(text: str, start: datetime, end: datetime) -> str:
    """``text`` with the values of the webinar's date put in; an unknown ``{event_…}`` fails.

    >>> start, end = datetime(2026, 11, 3, 18, 30), datetime(2026, 11, 3, 20, 0)
    >>> fill("Ефір — {event_weekday}, {event_start}–{event_end}", start, end)
    'Ефір — вівторок, 18:30–20:00'
    """
    values = event_values(start, end)

    def value(match: re.Match[str]) -> str:
        assert match.group(1) in values, f"unknown value {match.group(0)} in copy.md"
        return values[match.group(1)]

    return _EVENT_VALUE.sub(value, text)


def copy_text(start: datetime | None = None, end: datetime | None = None) -> str:
    """docs/copy.md with the webinar's date put in: of the test application unless given."""
    return fill(raw_copy_text(), start or EVENT_START, end or EVENT_END)


def own_sections(text: str) -> dict[str, str]:
    """Each section's own lines, up to the next heading of any level; ``""`` — before the first.

    >>> own_sections("Intro\\n## 6. Pages\\nA\\n### 6.1. Stream\\nB")
    {'': 'Intro', '6': 'A', '6.1': 'B'}
    """
    found: dict[str, list[str]] = {"": []}
    current = ""
    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            current = match.group(2)
            found[current] = []
            continue
        found[current].append(line)
    return {number: "\n".join(lines) for number, lines in found.items()}


def event_value_sections(text: str) -> set[str]:
    """Sections whose own lines hold a value ``{event_…}``.

    >>> sorted(event_value_sections("## 2. Success\\nSent on {event_date}\\n## 3. Letter\\nHi"))
    ['2']
    """
    return {number for number, lines in own_sections(text).items() if _EVENT_VALUE.search(lines)}


def value_names() -> frozenset[str]:
    """Names of every value the site, a letter or the bot puts in: copy.md, section 11."""
    rows = [line for line in section("11", raw_copy_text()).splitlines() if line.startswith("|")]
    first_cells = [row.strip().strip("|").split("|")[0] for row in rows[2:]]
    names = frozenset(name for cell in first_cells for name in _VALUE_NAME.findall(cell))
    assert names, "no values in copy.md, section 11"
    return names


def section(number: str, text: str | None = None) -> str:
    """Lines of section ``number`` (``"1.1"``, ``"10"``) up to the next heading of its level."""
    lines = (text if text is not None else copy_text()).splitlines()
    start = level = None
    for index, line in enumerate(lines):
        match = _HEADING.match(line)
        if match and match.group(2) == number:
            start, level = index + 1, len(match.group(1))
            break
    assert start is not None and level is not None, f"section {number} not found in copy.md"
    end = len(lines)
    for index in range(start, len(lines)):
        match = _HEADING.match(lines[index])
        if match and len(match.group(1)) <= level:
            end = index
            break
    return "\n".join(lines[start:end])


def group(section_text: str, name: str) -> str:
    """Lines after a line starting with ``**name**`` up to the next such bold line."""
    lines = section_text.splitlines()
    start = None
    for index, line in enumerate(lines):
        match = _BOLD_START.match(line)
        if match and match.group(1) == name:
            start = index + 1
            continue
        if start is not None and match:
            return "\n".join(lines[start:index])
    assert start is not None, f"group {name!r} not found"
    return "\n".join(lines[start:])


def labeled(text: str, label: str) -> list[str]:
    """Values of lines ``Label: value`` or ``- Label: value`` (plain text)."""
    pattern = re.compile(rf"^(?:- )?{re.escape(label)}: (.+)$")
    values = [plain(m.group(1)) for line in text.splitlines() if (m := pattern.match(line))]
    assert values, f"label {label!r} not found"
    return values


def one(text: str, label: str) -> str:
    values = labeled(text, label)
    assert len(values) == 1, f"label {label!r} found {len(values)} times"
    return values[0]


def table(text: str) -> dict[str, str]:
    """The first table in ``text``: first cell (plain) → second cell (plain)."""
    rows = [line for line in text.splitlines() if line.startswith("|")][2:]
    cells = [[plain(cell) for cell in row.strip().strip("|").split("|")] for row in rows]
    found = {row[0]: row[1] for row in cells if len(row) >= 2}
    assert found, "no table rows"
    return found


def kyiv_moment(value: str) -> datetime:
    """A moment written as ``28.10.2026, 19:00, пояс Europe/Kyiv`` (copy.md, section 4).

    >>> kyiv_moment("28.10.2026, 19:00, пояс Europe/Kyiv").isoformat()
    '2026-10-28T19:00:00+02:00'
    """
    match = _KYIV_MOMENT.fullmatch(plain(value))
    assert match is not None, f"not a moment: {value!r}"
    day, month, year, hour, minute, zone = match.groups()
    return datetime(int(year), int(month), int(day), int(hour), int(minute), tzinfo=ZoneInfo(zone))


def _is_mode_mark(line: str) -> bool:
    return line.strip() in {f"**{mode}**" for mode in MODES}


def mode_group(section_text: str, mode: str) -> str:
    """The list of the group ``mode``: the first line that is not a list item is shared again.

    >>> mode_group("**live**\\n\\n- A\\n\\n**replay**\\n\\n- B\\n\\nBoth:\\n\\n1. C", "replay")
    '\\n- B\\n'
    """
    lines = group(section_text, mode).splitlines()
    for index, line in enumerate(lines):
        if line.strip() and not _LIST_ITEM.match(line):
            return "\n".join(lines[:index])
    return "\n".join(lines)


def shared(section_text: str) -> str:
    """The section without the groups of modes: the text both modes show.

    >>> shared("Title: T\\n**live**\\n- A\\n**replay**\\n- B\\nBoth:\\n1. C")
    'Title: T\\nBoth:\\n1. C'
    """
    kept: list[str] = []
    inside = False
    for line in section_text.splitlines():
        if _is_mode_mark(line):
            inside = True
            continue
        if inside and (not line.strip() or _LIST_ITEM.match(line)):
            continue
        inside = False
        kept.append(line)
    return "\n".join(kept)


def units(markdown: str) -> list[str]:
    """Text units of copy.md lines as a page shows them: values of labels, list items,
    paragraphs, titles in bold or italics, table cells. Notes and the likes goal are left out.

    >>> units("- Заголовок: **Bold** title\\nПодання: a note\\n2. An [item](/x)\\n| A | `b` |")
    ['Bold title', 'An item', 'A', 'b']
    """
    texts: list[str] = []
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line or line.startswith(NOTES) or _LIKES_GOAL.match(line) or _TABLE_RULE.match(line):
            continue
        if line.startswith("|"):
            texts.extend(plain(cell) for cell in line.strip("|").split("|"))
            continue
        item = _LIST_ITEM.match(line)
        body = item.group(1) if item else line
        label = next((name for name in LABELS if body.startswith(f"{name}: ")), None)
        texts.append(plain(body.removeprefix(f"{label}: ") if label else body))
    return texts


def block_texts(number: str, mode: str) -> list[str]:
    """Every text of block ``number`` (``"1.2"``–``"1.7"``) the page shows in ``mode``, except the
    likes goal: the shared text and, if the block has groups of modes, the group of ``mode``."""
    text = section(number)
    by_mode = any(_is_mode_mark(line) for line in text.splitlines())
    return units(shared(text)) + (units(mode_group(text, mode)) if by_mode else [])


def likes_goal() -> tuple[date, str]:
    """The last day the likes goal of 1.2 is shown, and its text.

    The day comes from the line itself: «показується до 30.10.2026 включно».
    """
    found = [m for line in section("1.2").splitlines() if (m := _LIKES_GOAL.match(line))]
    assert len(found) == 1, "the likes goal must appear once in 1.2"
    day, month, year, text = found[0].groups()
    return date(int(year), int(month), int(day)), plain(text)
