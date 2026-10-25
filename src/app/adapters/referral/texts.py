"""Texts of ``_referral.html``: docs/copy.md 12.1, read once at startup, verbatim.

A missing part stops the application, as a missing legal text does.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from app.adapters.content.legal import ContentError

COPY_FILE = "copy.md"
SECTION = "12.1"
COUNT_PLACEHOLDER = "{referrals}"

_HEADING = re.compile(r"^(#{2,3}) (\d+(?:\.\d+)?)\. ")
_LABELLED = re.compile(r"^- ([^:]+): (.+)$")

LABELS = {
    "title": "Заголовок",
    "intro": "Текст",
    "label": "Підпис поля",
    "copy": "Кнопка",
    "copied": "Кнопка після копіювання",
    "counter": "Лічильник",
}


@dataclass(frozen=True, slots=True)
class ReferralTexts:
    title: str
    intro: str
    label: str
    copy: str
    copied: str
    counter: str  # with ``{referrals}``

    def count_line(self, referred: int) -> str:
        return self.counter.replace(COUNT_PLACEHOLDER, str(referred))


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


def load_texts(docs_dir: Path) -> ReferralTexts:
    """The texts of the part, from ``docs_dir/copy.md``."""
    path = docs_dir / COPY_FILE
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise ContentError(
            f"Text not found: {path} (docs/ is read from the working directory)"
        ) from None
    except (OSError, UnicodeDecodeError) as error:
        raise ContentError(f"Text cannot be read: {path} ({type(error).__name__})") from None
    found = {
        match.group(1): match.group(2).strip()
        for line in _section(text.splitlines())
        if (match := _LABELLED.match(line))
    }
    missing = [label for label in LABELS.values() if label not in found]
    if missing:
        raise ContentError(f"{COPY_FILE} {SECTION}: no {missing}")
    return ReferralTexts(**{name: found[label] for name, label in LABELS.items()})
