"""Page texts of the foundation from docs/copy.md and docs/materials.md, read once at startup.

- section 1.1 — the first screen, in the groups ``live`` and ``replay``: the route ``/`` gives
  the page the texts of the current mode ready (docs/requirements.md, section 3);
- sections 1.2–1.7 — the other blocks of the landing: a text in a group of a mode belongs to
  that mode, a text outside the groups to both; inline formatting becomes safe HTML. Every
  render of a page gets them for the mode and the day as ``blocks`` (CLAUDE.md, «Маршрут /»);
- section 10 — the service tags of ``/`` by mode, the shared ones, the event markup and the
  titles of service pages (requirements, section 13);
- section 13 — the page of the course ``/course`` (``load_course_texts``): its own texts and
  service tags; the values ``{lesson_…}`` come from ``LESSON_START`` the same way;
- docs/materials.md — the materials page, whole.

Texts are taken verbatim; a missing section, group or label stops the application, as a
missing legal text does. The date of the webinar is not written in the texts: they carry values
``{event_…}`` (copy.md, section 11), put in here from ``EVENT_START`` and ``EVENT_END``
(``app.core.event_values``), so pages and service tags get the texts ready. A value the
foundation does not know stops the application too. The text oracle (tests/copy_oracle.py)
reads the same documents and formats the values on its own, so a mistake here shows up as a
difference.
"""

import re
from dataclasses import dataclass, fields, replace
from datetime import date, datetime
from itertools import pairwise
from pathlib import Path

from markupsafe import Markup

from app.adapters.content.legal import ContentError, render_document, render_inline
from app.core.event_values import PREFIX, EventValues, event_values
from app.settings import SiteMode

COPY_FILE = "copy.md"
MATERIALS_FILE = "materials.md"
MODES: tuple[SiteMode, ...] = ("live", "replay")
FIRST_SCREEN_SECTION = "1.1"
SERVICE_SECTION = "10"
SHARED_GROUP = "Спільне"
EVENT_GROUP = "Розмітка події"
SERVICE_PAGES_GROUP = "Службові сторінки"
MATERIALS_PAGE = "Сторінка матеріалів"

ON_AIR_SECTION = "1.2"
AUDIENCE_SECTION = "1.3"
BENEFITS_SECTION = "1.4"
CHANNEL_SECTION = "1.5"
PRESENTER_SECTION = "1.6"
COURSE_SECTION = "1.7"
TITLE = "Заголовок"
INTRO = "Вступ"
TEXT = "Текст"
AUDIENCE_SUBTITLE = "Підзаголовок"
AUDIENCE_NOTE = "Примітка під текстом"
CHANNEL_LINK = "Посилання"
PRESENTER_NAME = "Ім'я"
PRESENTATION = "Подання"
LIKES_GOAL = "Окремий рядок під пунктами (показується до ДД.ММ.РРРР включно)"

_HEADING = re.compile(r"^(#{2,3}) (\d+(?:\.\d+)?)\. ")
_GROUP = re.compile(r"^\*\*(.+?)\*\*")
_LIST_ITEM = re.compile(r"^(?:- |\d+\. )(.+)$")
_LIKES_GOAL = re.compile(
    r"^Окремий рядок під пунктами \(показується до (\d{2})\.(\d{2})\.(\d{4}) включно\): (.+)$"
)
_COURSE_PART = re.compile(r"^\*\*(.+)\*\*$")  # a section of the accordion in 1.7
_PROGRAM_BLOCK = re.compile(r"^\*([^*].*)\*$")  # a block of «Програма», in italics
_ALWAYS_VISIBLE = re.compile(r"([^.]*)видно завжди")
_QUOTED = re.compile(r"«([^»]+)»")
_VALUE = re.compile(r"\{([^{}\s]+)\}")  # a value the site puts in: «{event_date}»
EVENT_VALUE_NAMES = frozenset(f"{PREFIX}{field.name}" for field in fields(EventValues))
LESSON_VALUE_NAMES = frozenset({"lesson_weekday", "lesson_date", "lesson_start"})  # section 13 only
COURSE_SECTION_NUMBER = "13"
COURSE_FIRST_SCREEN = "13.1"
COURSE_FORM = "13.2"
COURSE_HOW = "13.3"
COURSE_JOIN = "13.4"
COURSE_AUDIENCE = "13.5"
COURSE_RECORD = "13.6"
COURSE_SERVICE = "13.7"
NOTE_UNDER_LIST = "Примітка під списком"
LINK_LABEL = "Посилання"
_LINK_URL = re.compile(r"`([^`]+)`")


@dataclass(frozen=True, slots=True)
class FirstScreen:
    """The first screen of one mode; the names are the context of ``/`` (CLAUDE.md)."""

    eyebrow: str  # «Надзаголовок»
    title: str  # «Заголовок»
    subtitle: str  # «Підзаголовок»
    when: str  # «Коли»
    host: str  # «Ведучий»
    button: str  # «Кнопка»
    note: str  # «Під кнопкою»


@dataclass(frozen=True, slots=True)
class ServiceTexts:
    """``title``, ``description`` and the link card texts of ``/`` in one mode."""

    title: str
    description: str
    og_title: str
    og_description: str


@dataclass(frozen=True, slots=True)
class EventTexts:
    """Texts of the schema.org ``Event``; its times come from ``EVENT_START``/``EVENT_END``."""

    name: str
    description: str
    organizer: str
    in_language: str


@dataclass(frozen=True, slots=True)
class OnAir:
    """1.2 «Що в ефірі / Що в записі»; ``likes_goal`` is ``None`` after its last day."""

    title: Markup
    intro: Markup
    items: tuple[Markup, ...]
    likes_goal: Markup | None


@dataclass(frozen=True, slots=True)
class Audience:
    """1.3 «Для кого»: the items, then «Що треба знати» with its text and the note."""

    title: Markup
    items: tuple[Markup, ...]
    subtitle: Markup
    text: Markup
    note: Markup


@dataclass(frozen=True, slots=True)
class Benefits:
    """1.4 «Що ви отримаєте»."""

    title: Markup
    items: tuple[Markup, ...]


@dataclass(frozen=True, slots=True)
class Channel:
    """1.5 the Telegram channel; ``link`` is a ready ``<a>``."""

    title: Markup
    text: Markup
    link: Markup


@dataclass(frozen=True, slots=True)
class Presenter:
    """1.6 «Ведучий»."""

    title: Markup
    name: Markup
    text: Markup


@dataclass(frozen=True, slots=True)
class ProgramBlock:
    """A block of «Програма» that opens on its own; ``html`` — its lessons, numbered on."""

    title: Markup
    html: Markup


@dataclass(frozen=True, slots=True)
class CourseSection:
    """A section of the course accordion; ``always_visible`` by «Подання» in copy.md, 1.7.

    ``html`` is the text before the blocks: all of it in every section but «Програма», whose
    text is its ``blocks``.
    """

    title: Markup
    html: Markup
    always_visible: bool
    blocks: tuple[ProgramBlock, ...]


@dataclass(frozen=True, slots=True)
class Course:
    """1.7 «Курс»: the title and the intro always visible, then the sections of the accordion."""

    title: Markup
    intro: Markup
    sections: tuple[CourseSection, ...]


@dataclass(frozen=True, slots=True)
class LandingBlocks:
    """Blocks 1.2–1.7 of one mode, ready: ``blocks`` in page templates (CLAUDE.md)."""

    on_air: OnAir
    audience: Audience
    benefits: Benefits
    channel: Channel
    presenter: Presenter
    course: Course


@dataclass(frozen=True, slots=True)
class LandingTexts:
    """Blocks 1.2–1.7 of one mode as read, the likes goal included, and its last day."""

    blocks: LandingBlocks
    likes_goal_until: date

    def for_day(self, today: date) -> LandingBlocks:
        """The blocks for ``today`` (a Kyiv date): the likes goal goes after its last day."""
        if today <= self.likes_goal_until:
            return self.blocks
        return replace(self.blocks, on_air=replace(self.blocks.on_air, likes_goal=None))


@dataclass(frozen=True, slots=True)
class CourseHero:
    """13.1 the first screen of ``/course``; ``when`` is ``None`` without ``LESSON_START``."""

    eyebrow: str
    title: str
    subtitle: str
    when: str | None
    host: str
    button: str
    note: str


@dataclass(frozen=True, slots=True)
class CourseList:
    """13.3 «Як проходить курс» and 13.5 «Для кого» (with its note): a title and a list."""

    title: Markup
    items: tuple[Markup, ...]
    note: Markup | None


@dataclass(frozen=True, slots=True)
class CourseLink:
    """A text that leads to ``url``."""

    text: Markup
    url: str


@dataclass(frozen=True, slots=True)
class CourseJoin:
    """13.4 «Як приєднатися»: the title, the text and the link to the CBS page."""

    title: Markup
    text: Markup
    link: CourseLink


@dataclass(frozen=True, slots=True)
class CourseTexts:
    """Section 13 of copy.md: every text of ``/course`` except blocks 1.6 and 1.7."""

    hero: CourseHero
    form_title: Markup
    form_intro: Markup
    how: CourseList
    join: CourseJoin
    audience: CourseList
    record: CourseLink
    service: ServiceTexts


@dataclass(frozen=True, slots=True)
class PageTexts:
    first_screen: dict[SiteMode, FirstScreen]
    landing: dict[SiteMode, LandingTexts]
    service: dict[SiteMode, ServiceTexts]
    site_name: str
    image_alt: str
    event: EventTexts
    materials_title: str
    materials_html: Markup


FIRST_SCREEN_LABELS = {
    "eyebrow": "Надзаголовок",
    "title": "Заголовок",
    "subtitle": "Підзаголовок",
    "when": "Коли",
    "host": "Ведучий",
    "button": "Кнопка",
    "note": "Під кнопкою",
}
SERVICE_TAGS = {
    "title": "title",
    "description": "description",
    "og_title": "og:title",
    "og_description": "og:description",
}
EVENT_FIELDS = {
    "name": "name",
    "description": "description",
    "organizer": "organizer",
    "in_language": "inLanguage",
}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise ContentError(
            f"Page text not found: {path} (docs/ is read from the working directory)"
        ) from None
    except (OSError, UnicodeDecodeError) as error:
        raise ContentError(f"Page text cannot be read: {path} ({type(error).__name__})") from None


def _fill(
    lines: list[str],
    event: EventValues | None,
    number: str,
    lesson: dict[str, str] | None = None,
) -> list[str]:
    """``lines`` with the values of the webinar's date put in; an unknown value stops the app.

    Without ``event`` (the redirect stub: no ``EVENT_*``, no page rendered) the values the
    foundation knows stay as written. The values ``{lesson_…}`` are known in section 13 only;
    without ``lesson`` (no ``LESSON_START``) they stay as written.
    """
    values = event.placeholders() if event is not None else {}
    known = EVENT_VALUE_NAMES
    if number.split(".")[0] == COURSE_SECTION_NUMBER:
        values = values | (lesson or {})
        known = known | LESSON_VALUE_NAMES

    def value(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in known:
            raise ContentError(f"{COPY_FILE}: unknown value «{match.group(0)}» in section {number}")
        return values.get(name, match.group(0))

    return [_VALUE.sub(value, line) for line in lines]


def _section(
    lines: list[str],
    number: str,
    event: EventValues | None,
    lesson: dict[str, str] | None = None,
) -> list[str]:
    """Lines of section ``number`` (``1.1``, ``10``) up to the next heading of its level,
    with the values of the webinar's date put in: every section is read through here."""
    for index, line in enumerate(lines):
        match = _HEADING.match(line)
        if match and match.group(2) == number:
            level = len(match.group(1))
            end = next(
                (
                    later
                    for later in range(index + 1, len(lines))
                    if (heading := _HEADING.match(lines[later])) and len(heading.group(1)) <= level
                ),
                len(lines),
            )
            return _fill(lines[index + 1 : end], event, number, lesson)
    raise ContentError(f"{COPY_FILE}: section {number} not found")


def _group(lines: list[str], name: str, where: str) -> list[str]:
    """Lines after a line that starts with ``**name**`` up to the next such line."""
    starts = [i for i, line in enumerate(lines) if (m := _GROUP.match(line)) and m.group(1) == name]
    if not starts:
        raise ContentError(f"{COPY_FILE}: group «{name}» not found in section {where}")
    start = starts[0] + 1
    end = next((i for i in range(start, len(lines)) if _GROUP.match(lines[i])), len(lines))
    return lines[start:end]


def _labelled(lines: list[str], label: str, where: str) -> str:
    """The value of the only item ``- label: value`` or line ``label: value``."""
    prefixes = (f"- {label}: ", f"{label}: ")
    values = [line.split(": ", 1)[1].strip() for line in lines if line.startswith(prefixes)]
    if len(values) != 1 or not values[0]:
        raise ContentError(f"{COPY_FILE}: «{label}» must appear once in {where}")
    return values[0]


def _inline(lines: list[str], label: str, where: str) -> Markup:
    return render_inline(_labelled(lines, label, where))


def _is_mode_mark(line: str) -> bool:
    return (match := _GROUP.match(line)) is not None and match.group(1) in MODES


def _mode_group(lines: list[str], mode: SiteMode, where: str) -> list[str]:
    """The list of the group ``mode``: the first line that is not a list item is shared again.

    >>> _mode_group(["**live**", "- A", "**replay**", "- B", "", "Both:", "1. C"], "replay", "")
    ['- B', '']
    """
    group = _group(lines, mode, where)
    end = next(
        (i for i, line in enumerate(group) if line.strip() and not _LIST_ITEM.match(line)),
        len(group),
    )
    return group[:end]


def _shared(lines: list[str]) -> list[str]:
    """Lines outside the groups of modes: the text both modes show.

    >>> _shared(["Title: T", "**live**", "- A", "**replay**", "- B", "Both:", "1. C"])
    ['Title: T', 'Both:', '1. C']
    """
    kept: list[str] = []
    inside = False
    for line in lines:
        if _is_mode_mark(line):
            inside = True
            continue
        if inside and (not line.strip() or _LIST_ITEM.match(line)):
            continue
        inside = False
        kept.append(line)
    return kept


def _items(lines: list[str], where: str) -> tuple[Markup, ...]:
    """The list items of ``lines`` as inline HTML; at least one."""
    items = tuple(render_inline(m.group(1)) for line in lines if (m := _LIST_ITEM.match(line)))
    if not items:
        raise ContentError(f"{COPY_FILE}: no items in {where}")
    return items


def _likes_goal(lines: list[str]) -> tuple[Markup, date]:
    """The likes goal of 1.2 and the last day it is shown, from the line's own label."""
    found = [match for line in lines if (match := _LIKES_GOAL.match(line))]
    if len(found) != 1:
        raise ContentError(f"{COPY_FILE}: «{LIKES_GOAL}» must appear once in {ON_AIR_SECTION}")
    day, month, year, text = found[0].groups()
    try:
        last_day = date(int(year), int(month), int(day))
    except ValueError:
        raise ContentError(f"{COPY_FILE}: «{LIKES_GOAL}» has no real date") from None
    return render_inline(text), last_day


def _audience(lines: list[str]) -> Audience:
    where = AUDIENCE_SECTION
    labels = tuple(f"{label}: " for label in (TITLE, AUDIENCE_SUBTITLE, AUDIENCE_NOTE))
    paragraphs = [
        line.strip()
        for line in lines
        if line.strip() and not _LIST_ITEM.match(line) and not line.startswith(labels)
    ]
    if len(paragraphs) != 1:
        raise ContentError(f"{COPY_FILE}: one paragraph without a label expected in {where}")
    return Audience(
        title=_inline(lines, TITLE, where),
        items=_items(lines, where),
        subtitle=_inline(lines, AUDIENCE_SUBTITLE, where),
        text=render_inline(paragraphs[0]),
        note=_inline(lines, AUDIENCE_NOTE, where),
    )


def _always_visible(presentation: str, titles: list[str]) -> frozenset[str]:
    """Sections named in «» in the sentence «… видно завжди» of «Подання»."""
    sentence = _ALWAYS_VISIBLE.search(presentation)
    if sentence is None:
        raise ContentError(f"{COPY_FILE}: «{PRESENTATION}» does not say what is always visible")
    names = _QUOTED.findall(sentence.group(1))
    for name in names:
        if name not in titles:
            raise ContentError(
                f"{COPY_FILE}: «{name}» in «{PRESENTATION}» is not a section of {COURSE_SECTION}"
            )
    return frozenset(names)


def _course_section(title: str, body: list[str], always_visible: bool) -> CourseSection:
    """A section of the accordion; the italic lines of «Програма» start its blocks."""
    starts = [i for i, line in enumerate(body) if _PROGRAM_BLOCK.match(line)]
    blocks = tuple(
        ProgramBlock(
            title=render_inline(body[start].strip("*")),
            html=render_document("\n".join(body[start + 1 : end])),
        )
        for start, end in pairwise([*starts, len(body)])
    )
    text = body[: starts[0]] if starts else body
    return CourseSection(
        title=render_inline(title),
        html=render_document("\n".join(text)),
        always_visible=always_visible,
        blocks=blocks,
    )


def _course(lines: list[str]) -> Course:
    where = COURSE_SECTION
    starts = [i for i, line in enumerate(lines) if _COURSE_PART.match(line)]
    if not starts:
        raise ContentError(f"{COPY_FILE}: no sections «**…**» in {where}")
    head = lines[: starts[0]]
    parts = [
        (lines[start].strip().strip("*"), lines[start + 1 : end])
        for start, end in pairwise([*starts, len(lines)])
    ]
    visible = _always_visible(_labelled(head, PRESENTATION, where), [t for t, _ in parts])
    return Course(
        title=_inline(head, TITLE, where),
        intro=_inline(head, INTRO, where),
        sections=tuple(_course_section(t, body, t in visible) for t, body in parts),
    )


def _landing(lines: list[str], event: EventValues | None) -> dict[SiteMode, LandingTexts]:
    """Blocks 1.2–1.7 of each mode."""
    on_air = _section(lines, ON_AIR_SECTION, event)
    on_air_shared = _shared(on_air)
    on_air_items = _items(on_air_shared, ON_AIR_SECTION)
    likes_goal, likes_goal_until = _likes_goal(on_air_shared)
    benefits = _section(lines, BENEFITS_SECTION, event)
    benefits_title = _inline(_shared(benefits), TITLE, BENEFITS_SECTION)
    channel = _section(lines, CHANNEL_SECTION, event)
    presenter = _section(lines, PRESENTER_SECTION, event)
    # The same in both modes.
    audience = _audience(_section(lines, AUDIENCE_SECTION, event))
    channel_block = Channel(
        title=_inline(channel, TITLE, CHANNEL_SECTION),
        text=_inline(channel, TEXT, CHANNEL_SECTION),
        link=_inline(channel, CHANNEL_LINK, CHANNEL_SECTION),
    )
    presenter_block = Presenter(
        title=_inline(presenter, TITLE, PRESENTER_SECTION),
        name=_inline(presenter, PRESENTER_NAME, PRESENTER_SECTION),
        text=_inline(presenter, TEXT, PRESENTER_SECTION),
    )
    course = _course(_section(lines, COURSE_SECTION, event))
    landing: dict[SiteMode, LandingTexts] = {}
    for mode in MODES:
        on_air_group = _mode_group(on_air, mode, ON_AIR_SECTION)
        where = f"{ON_AIR_SECTION} «{mode}»"
        blocks = LandingBlocks(
            on_air=OnAir(
                title=_inline(on_air_group, TITLE, where),
                intro=_inline(on_air_group, INTRO, where),
                items=on_air_items,
                likes_goal=likes_goal,
            ),
            audience=audience,
            benefits=Benefits(
                title=benefits_title,
                items=_items(
                    _mode_group(benefits, mode, BENEFITS_SECTION), f"{BENEFITS_SECTION} «{mode}»"
                ),
            ),
            channel=channel_block,
            presenter=presenter_block,
            course=course,
        )
        landing[mode] = LandingTexts(blocks=blocks, likes_goal_until=likes_goal_until)
    return landing


def _table(lines: list[str]) -> dict[str, str]:
    """Body rows of a two-column table: the first cell without backticks → the second."""
    rows = [line for line in lines if line.startswith("|")][2:]
    cells = [[cell.strip() for cell in row.strip().strip("|").split("|")] for row in rows]
    return {row[0].strip("`"): row[1] for row in cells if len(row) >= 2}


def _cell(table: dict[str, str], key: str, where: str) -> str:
    value = table.get(key, "")
    if not value:
        raise ContentError(f"{COPY_FILE}: «{key}» not found in {where}")
    return value


def _link(value: str, where: str) -> CourseLink:
    """``text → `address```: the words before the arrow lead to the address after it."""
    text, arrow, rest = value.partition(" → ")
    found = _LINK_URL.search(rest)
    if not arrow or found is None:
        raise ContentError(f"{COPY_FILE}: «text → `address`» expected in {where}")
    return CourseLink(text=render_inline(text), url=found.group(1))


def _course_list(lines: list[str], where: str, *, note: bool) -> CourseList:
    return CourseList(
        title=_inline(lines, TITLE, where),
        items=_items(lines, where),
        note=_inline(lines, NOTE_UNDER_LIST, where) if note else None,
    )


def load_course_texts(docs_dir: Path, *, lesson_start: datetime | None) -> CourseTexts:
    """Read section 13 of copy.md, the texts of ``/course``.

    ``lesson_start`` — ``LESSON_START`` (naive Kyiv wall time): it fills the values
    ``{lesson_…}``; without it the line «Коли» is not shown.
    """
    lesson = None
    if lesson_start is not None:
        values = event_values(lesson_start, lesson_start)
        lesson = {
            "lesson_weekday": values.weekday,
            "lesson_date": values.date,
            "lesson_start": values.start,
        }
    lines = _read(docs_dir / COPY_FILE).splitlines()

    def part(number: str) -> list[str]:
        return _section(lines, number, None, lesson)

    first = part(COURSE_FIRST_SCREEN)
    texts = {
        name: _labelled(first, label, COURSE_FIRST_SCREEN)
        for name, label in FIRST_SCREEN_LABELS.items()
        if name != "when"
    }
    when = _labelled(first, FIRST_SCREEN_LABELS["when"], COURSE_FIRST_SCREEN)
    form = part(COURSE_FORM)
    join = part(COURSE_JOIN)
    service = _table(part(COURSE_SERVICE))
    return CourseTexts(
        hero=CourseHero(when=when if lesson is not None else None, **texts),
        form_title=_inline(form, TITLE, COURSE_FORM),
        form_intro=_inline(form, INTRO, COURSE_FORM),
        how=_course_list(part(COURSE_HOW), COURSE_HOW, note=False),
        join=CourseJoin(
            title=_inline(join, TITLE, COURSE_JOIN),
            text=_inline(join, TEXT, COURSE_JOIN),
            link=_link(_labelled(join, LINK_LABEL, COURSE_JOIN), COURSE_JOIN),
        ),
        audience=_course_list(part(COURSE_AUDIENCE), COURSE_AUDIENCE, note=True),
        record=_link(_labelled(part(COURSE_RECORD), TEXT, COURSE_RECORD), COURSE_RECORD),
        service=ServiceTexts(
            **{name: _cell(service, tag, COURSE_SERVICE) for name, tag in SERVICE_TAGS.items()}
        ),
    )


def load_page_texts(docs_dir: Path, *, event: EventValues | None) -> PageTexts:
    """Read the texts of ``/`` and of the materials page from ``docs_dir``.

    ``event`` — the values of the webinar's date from the settings; ``None`` only in the
    redirect stub, which has no ``EVENT_*``.
    """
    lines = _read(docs_dir / COPY_FILE).splitlines()
    first = _section(lines, FIRST_SCREEN_SECTION, event)
    service = _section(lines, SERVICE_SECTION, event)
    first_screen: dict[SiteMode, FirstScreen] = {}
    service_texts: dict[SiteMode, ServiceTexts] = {}
    for mode in MODES:
        where = f"{FIRST_SCREEN_SECTION} «{mode}»"
        group = _group(first, mode, FIRST_SCREEN_SECTION)
        first_screen[mode] = FirstScreen(
            **{name: _labelled(group, label, where) for name, label in FIRST_SCREEN_LABELS.items()}
        )
        where = f"{SERVICE_SECTION} «{mode}»"
        table = _table(_group(service, mode, SERVICE_SECTION))
        service_texts[mode] = ServiceTexts(
            **{name: _cell(table, tag, where) for name, tag in SERVICE_TAGS.items()}
        )
    shared = _table(_group(service, SHARED_GROUP, SERVICE_SECTION))
    markup = _table(_group(service, EVENT_GROUP, SERVICE_SECTION))
    pages = _table(_group(service, SERVICE_PAGES_GROUP, SERVICE_SECTION))
    return PageTexts(
        first_screen=first_screen,
        landing=_landing(lines, event),
        service=service_texts,
        site_name=_cell(shared, "og:site_name", SHARED_GROUP),
        image_alt=_cell(shared, "og:image:alt", SHARED_GROUP),
        event=EventTexts(
            **{name: _cell(markup, field, EVENT_GROUP) for name, field in EVENT_FIELDS.items()}
        ),
        materials_title=_cell(pages, MATERIALS_PAGE, SERVICE_PAGES_GROUP),
        materials_html=render_document(_read(docs_dir / MATERIALS_FILE)),
    )
