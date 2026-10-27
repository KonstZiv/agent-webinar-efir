"""Texts of ``/checkin``: docs/copy.md, sections 14.1 and 14.2, read once at startup, verbatim.

A missing part stops the application, as a missing legal text does. The text of the error for
an unknown address holds a link in Markdown, ``[text](/path)``; it becomes a safe ``<a>``.
"""

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from markupsafe import Markup, escape

from app.adapters.content.legal import ContentError
from app.core.checkin.service import Problem
from app.core.event_values import MONTHS

COPY_FILE = "copy.md"
PAGE_SECTION = "14.1"
TAGS_SECTION = "14.2"

_HEADING = re.compile(r"^(#{2,3}) (\d+(?:\.\d+)?)\. ")
_BULLET = re.compile(r"^- ([^:]+): (.+)$")
_ROW = re.compile(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|$")
_LINK = re.compile(r"\[([^\]]+)\]\((/[^)\s]*)\)")
_EDGES = re.compile(r"«([^»]+)»")

_PARTS = {"Поля і підписи:": "fields", "Успіх:": "success", "Помилки:": "errors"}
_PROBLEM_LABELS = {
    Problem.CODE_EMPTY: "Код порожній",
    Problem.CODE_INVALID: "Код не підходить або чек-ін закритий",
    Problem.EMAIL_EMPTY: "Поле пошти порожнє",
    Problem.EMAIL_FORMAT: "Адреса має неправильний формат",
    Problem.EMAIL_UNKNOWN: "Адреси немає серед зареєстрованих",
    Problem.QUESTION_TOO_LONG: "Запитання довше за 500 знаків",
    Problem.TOO_MANY: "Забагато спроб поспіль",
    Problem.RATING_INVALID: "Помилка мережі або сервера",  # no choice of the form gives it
    Problem.FAILED: "Помилка мережі або сервера",
}


def day_month(day: date) -> str:
    """``2 листопада``: the day and the month of a date, as copy.md writes ``{lesson_day_month}``.

    >>> day_month(date(2026, 11, 2))
    '2 листопада'
    """
    return f"{day.day} {MONTHS[day.month - 1]}"


def inline(text: str) -> Markup:
    """The text as safe HTML: escaped, with ``[text](/path)`` as a link to the same site."""
    parts: list[Markup] = []
    position = 0
    for link in _LINK.finditer(text):
        parts.append(escape(text[position : link.start()]))
        parts.append(Markup('<a href="{}">{}</a>').format(link.group(2), link.group(1)))
        position = link.end()
    parts.append(escape(text[position:]))
    return Markup("").join(parts)


@dataclass(frozen=True, slots=True)
class CheckinTexts:
    title: str
    intro: str
    code_label: str
    code_placeholder: str
    email_label: str
    email_placeholder: str
    email_hint: str
    rating_label: str
    rating_low: str
    rating_high: str
    question_label: str
    button: str
    button_busy: str
    success_title: str
    success_text: str
    success_feedback: str
    errors: dict[str, Markup]
    tag_title: str
    tag_description: str

    def success(self, lesson_date: date, email: str) -> str:
        """The success line for the lesson of ``lesson_date`` and the participant's address."""
        return self.success_text.replace("{lesson_day_month}", day_month(lesson_date)).replace(
            "{email}", email
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


def _section(lines: list[str], number: str) -> list[str]:
    start = None
    for index, line in enumerate(lines):
        match = _HEADING.match(line)
        if start is None:
            if match and match.group(2) == number:
                start = index + 1
        elif match:
            return lines[start:index]
    if start is None:
        raise ContentError(f"Section {number} not found in {COPY_FILE}")
    return lines[start:]


def _parts(lines: list[str]) -> dict[str, dict[str, str]]:
    """Labelled bullets and table rows of a section, by the part they stand in."""
    found: dict[str, dict[str, str]] = {"page": {}, "fields": {}, "success": {}, "errors": {}}
    part = "page"
    for line in lines:
        text = line.strip()
        if text in _PARTS:
            part = _PARTS[text]
        elif match := _BULLET.match(text):
            found[part][match.group(1)] = match.group(2).strip()
        elif (row := _ROW.match(text)) and not set(row.group(1)) <= set(":- "):
            found[part][row.group(1).strip("` ")] = row.group(2).strip()
    return found


def _need(found: dict[str, str], label: str, where: str) -> str:
    if label not in found:
        raise ContentError(f"{COPY_FILE} {where}: no «{label}»")
    return found[label]


def load_texts(docs_dir: Path) -> CheckinTexts:
    """The texts of the page and its tags, from ``docs_dir/copy.md``."""
    lines = _read(docs_dir / COPY_FILE).splitlines()
    parts = _parts(_section(lines, PAGE_SECTION))
    tags = _parts(_section(lines, TAGS_SECTION))["page"]
    page, fields = parts["page"], parts["fields"]
    success, errors = parts["success"], parts["errors"]
    where = PAGE_SECTION
    edges = _EDGES.findall(_need(fields, "Оцінка: варіанти", where))
    if len(edges) != 2:
        raise ContentError(f"{COPY_FILE} {where}: «Оцінка: варіанти» needs two edge labels")
    return CheckinTexts(
        title=_need(page, "Заголовок", where),
        intro=_need(page, "Вступ", where),
        code_label=_need(fields, "Поле код: підпис", where),
        code_placeholder=_need(fields, "Поле код: підказка в полі", where),
        email_label=_need(fields, "Поле пошти: підпис", where),
        email_placeholder=_need(fields, "Поле пошти: підказка в полі", where),
        email_hint=_need(fields, "Поле пошти: пояснення під полем", where),
        rating_label=_need(fields, "Оцінка: підпис", where),
        rating_low=edges[0],
        rating_high=edges[1],
        question_label=_need(fields, "Запитання: підпис", where),
        button=_need(fields, "Кнопка", where),
        button_busy=_need(fields, "Кнопка під час надсилання", where),
        success_title=_need(success, "Заголовок", where),
        success_text=_need(success, "Текст", where),
        success_feedback=_need(success, "Текст, якщо передано оцінку або запитання", where),
        errors={
            problem.value: inline(_need(errors, label, where))
            for problem, label in _PROBLEM_LABELS.items()
        },
        tag_title=_need(tags, "title", TAGS_SECTION),
        tag_description=_need(tags, "description", TAGS_SECTION),
    )
