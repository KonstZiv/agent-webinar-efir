"""The slice «мінітест рівня»: five questions on the success screen, the level in the database.

``install`` provides the slice's services by key (``app.adapters.quiz.keys``) and gives
``_quiz.html`` its values (template global ``quiz``). The questions (docs/quiz.md) and the texts
(docs/copy.md, 12.3) are read at startup; the level is written through the application's engine.
The permission to answer is a signed ticket, made with ``UNSUBSCRIBE_SECRET``.
"""

from pathlib import Path

from app.adapters.quiz.keys import CONTENT, LEVELS, QUIZ, TEXTS
from app.adapters.quiz.levels import SqlLevelStore
from app.adapters.quiz.texts import load_quiz, load_texts
from app.adapters.quiz.view import QuizPartial
from app.core.quiz.service import LevelQuiz
from app.services import CLOCK
from app.slices import SliceSetup

# Texts live in the repository's docs/; the working directory is the repository (as in main.py).
DOCS_DIR = Path("docs")


def install(setup: SliceSetup) -> None:
    services = setup.services
    content = load_quiz(DOCS_DIR)
    texts = load_texts(DOCS_DIR)

    def scenario() -> LevelQuiz:
        secret = setup.settings.unsubscribe_secret
        if secret is None:
            raise RuntimeError("UNSUBSCRIBE_SECRET is required in normal operation")
        return LevelQuiz(
            content, services.get(LEVELS), services.get(CLOCK), secret.get_secret_value()
        )

    setup.provide(LEVELS, lambda: SqlLevelStore(setup.engine()))
    setup.provide(QUIZ, scenario)
    setup.provide(CONTENT, lambda: content)
    setup.provide(TEXTS, lambda: texts)
    setup.template_global(
        "quiz", QuizPartial(content, texts, lambda email: services.get(QUIZ).ticket(email))
    )
