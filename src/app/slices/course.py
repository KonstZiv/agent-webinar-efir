"""The slice «course»: the page ``/course`` for advertising traffic (docs/copy.md, section 13).

``install`` reads the texts of section 13 once, with the values ``{lesson_…}`` from
``LESSON_START``, and provides them by the key ``course.texts`` to the route. The registration,
the letter and the counters are not touched: the page uses the form of the slice «реєстрація і
лист».
"""

from pathlib import Path

from app.adapters.content.copy import load_course_texts
from app.adapters.web.routers.course import COURSE_PAGE, COURSE_TEXTS, page_context
from app.slices import SliceSetup

# Texts live in the repository's docs/; the working directory is the repository (as in main.py).
DOCS_DIR = Path("docs")


def install(setup: SliceSetup) -> None:
    texts = load_course_texts(DOCS_DIR, lesson_start=setup.settings.lesson_start)
    setup.provide(COURSE_TEXTS, lambda: texts)
    setup.provide(COURSE_PAGE, lambda: lambda container: page_context(container, texts))
