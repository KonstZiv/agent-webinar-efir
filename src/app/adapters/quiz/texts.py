"""Texts of the quiz: the questions and results of docs/quiz.md, the interface of copy.md 12.3.

Read once at startup, verbatim; a missing part stops the application, as a missing legal text
does.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from app.adapters.content.legal import ContentError
from app.core.quiz.model import Option, Question, Quiz, Result

COPY_FILE = "copy.md"
QUIZ_FILE = "quiz.md"
SECTION = "12.3"
QUESTIONS_HEADING = "## Запитання"
RESULTS_HEADING = "## Результати"

_HEADING = re.compile(r"^(#{2,3}) (\d+(?:\.\d+)?)\. ")
_QUESTION = re.compile(r"^### \d+\. (.+)$")
_OPTION = re.compile(r"^- (.+) — ([012])$")
_LABELLED = re.compile(r"^- ([^:]+): (.+)$")
_RESULT_ROW = re.compile(
    r"^\|\s*(\d+)–(\d+)\s*\|\s*`(\w+)`\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$"
)

LABELS = {
    "title": "Заголовок",
    "intro": "Вступ",
    "button": "Кнопка",
    "incomplete": "Неповна відповідь",
    "not_saved": "Збій збереження",
    "expired": "Час минув",
}


@dataclass(frozen=True, slots=True)
class QuizTexts:
    title: str
    intro: str
    button: str
    incomplete: str
    not_saved: str
    expired: str


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


def load_texts(docs_dir: Path) -> QuizTexts:
    """The texts of the interface, from ``docs_dir/copy.md``."""
    found = {
        match.group(1): match.group(2).strip()
        for line in _section(_read(docs_dir / COPY_FILE).splitlines())
        if (match := _LABELLED.match(line))
    }
    missing = [label for label in LABELS.values() if label not in found]
    if missing:
        raise ContentError(f"{COPY_FILE} {SECTION}: no {missing}")
    return QuizTexts(**{name: found[label] for name, label in LABELS.items()})


def load_quiz(docs_dir: Path) -> Quiz:
    """The questions and results, from ``docs_dir/quiz.md``."""
    text = _read(docs_dir / QUIZ_FILE)
    if QUESTIONS_HEADING not in text or RESULTS_HEADING not in text:
        raise ContentError(f"{QUIZ_FILE}: no «{QUESTIONS_HEADING}» or «{RESULTS_HEADING}»")
    body, results_text = text.split(QUESTIONS_HEADING, 1)[1].split(RESULTS_HEADING, 1)
    questions: list[tuple[str, list[Option]]] = []
    for line in body.splitlines():
        if heading := _QUESTION.match(line):
            questions.append((heading.group(1), []))
        elif (option := _OPTION.match(line)) and questions:
            questions[-1][1].append(Option(option.group(1), int(option.group(2))))
    results = tuple(
        Result(
            level=match.group(3),
            name=match.group(4),
            advice=match.group(5),
            low=int(match.group(1)),
            high=int(match.group(2)),
        )
        for line in results_text.splitlines()
        if (match := _RESULT_ROW.match(line))
    )
    if not questions or not results or any(not options for _, options in questions):
        raise ContentError(f"{QUIZ_FILE}: no questions with options, or no results")
    return Quiz(tuple(Question(title, tuple(options)) for title, options in questions), results)
