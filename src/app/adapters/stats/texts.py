"""Texts of ``/stats``: docs/copy.md, section 12.2, and the level names of docs/quiz.md.

Read once at startup, verbatim; a missing section, label or table stops the application, as a
missing legal text does. The name of a level is the «Назва для людей» of the results table of
the quiz, found by its «Значення в базі»; the order is the table's.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from app.adapters.content.legal import ContentError

COPY_FILE = "copy.md"
QUIZ_FILE = "quiz.md"
SECTION = "12.2"
RESULTS_HEADING = "## Результати"

_HEADING = re.compile(r"^(#{2,3}) (\d+(?:\.\d+)?)\. ")
_LABELLED = re.compile(r"^- ([^:]+): (.+)$")
_RESULT_ROW = re.compile(r"^\|[^|]*\|\s*`(\w+)`\s*\|\s*([^|]+?)\s*\|")

LABELS = {
    "title": "Заголовок",
    "registrations": "Блок реєстрацій",
    "total": "Усього",
    "chart_title": "Блок графіка",
    "chart_caption": "Підпис графіка",
    "telegram_title": "Блок Telegram",
    "share": "Частка Telegram",
    "share_caption": "Підпис частки",
    "levels_title": "Блок рівнів",
    "unspecified": "Без рівня",
    "failure": "Збій",
}


@dataclass(frozen=True, slots=True)
class StatsTexts:
    """Every text of the page, verbatim; ``share_caption`` keeps ``{telegram}`` and ``{total}``."""

    title: str
    registrations: str
    total: str
    chart_title: str
    chart_caption: str
    telegram_title: str
    share: str
    share_caption: str
    levels_title: str
    unspecified: str
    failure: str

    def caption_of_share(self, telegram: int, total: int) -> str:
        return self.share_caption.replace("{telegram}", str(telegram)).replace(
            "{total}", str(total)
        )


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise ContentError(
            f"Text not found: {path} (docs/ is read from the working directory)"
        ) from None
    except (OSError, UnicodeDecodeError) as error:
        raise ContentError(f"Text cannot be read: {path} ({type(error).__name__})") from None


def _section(lines: list[str]) -> list[str]:
    start = None
    for index, line in enumerate(lines):
        match = _HEADING.match(line)
        if start is None:
            if match and match.group(2) == SECTION:
                start = index + 1
        elif match:
            return lines[start:index]
    if start is None:
        raise ContentError(f"Section {SECTION} not found in {COPY_FILE}")
    return lines[start:]


def load_texts(docs_dir: Path) -> StatsTexts:
    """The texts of the page, from ``docs_dir/copy.md``."""
    found = {
        match.group(1): match.group(2).strip()
        for line in _section(_read(docs_dir / COPY_FILE).splitlines())
        if (match := _LABELLED.match(line))
    }
    missing = [label for label in LABELS.values() if label not in found]
    if missing:
        raise ContentError(f"{COPY_FILE} {SECTION}: no {missing}")
    return StatsTexts(**{name: found[label] for name, label in LABELS.items()})


def load_level_names(docs_dir: Path) -> dict[str, str]:
    """Value in the database → the name for people, from the results of ``docs_dir/quiz.md``."""
    text = _read(docs_dir / QUIZ_FILE)
    if RESULTS_HEADING not in text:
        raise ContentError(f"{QUIZ_FILE}: no «{RESULTS_HEADING}»")
    matches = [_RESULT_ROW.match(line) for line in text.split(RESULTS_HEADING, 1)[1].splitlines()]
    names = {match.group(1): match.group(2) for match in matches if match}
    if not names:
        raise ContentError(f"{QUIZ_FILE}: the results table has no levels")
    return names
