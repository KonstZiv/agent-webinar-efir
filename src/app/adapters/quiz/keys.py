"""Services of the slice «мінітест рівня» by key (``app.services``), named ``quiz.*``.

The keys live here, not in ``app.slices.quiz``: the route imports them, and a route module must
import without the slice package (the foundation's tests swap ``app.slices`` for a sample).
"""

from app.adapters.quiz.texts import QuizTexts
from app.core.quiz.model import Quiz
from app.core.quiz.ports import LevelStore
from app.core.quiz.service import LevelQuiz
from app.services import Key

LEVELS = Key[LevelStore]("quiz.levels")
QUIZ = Key[LevelQuiz]("quiz.scenario")
CONTENT = Key[Quiz]("quiz.content")
TEXTS = Key[QuizTexts]("quiz.texts")
