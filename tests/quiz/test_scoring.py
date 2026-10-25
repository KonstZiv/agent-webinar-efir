"""The scoring of docs/quiz.md: the levels at the edges of the sums."""

from pathlib import Path

import pytest

from app.adapters.quiz.texts import load_quiz
from tests.conftest import REPO_ROOT
from tests.quiz.helpers import oracle

QUIZ = load_quiz(REPO_ROOT / "docs")
LEVELS = {result.level for result in oracle()[1]}


def choose(points: list[int]) -> list[int]:
    """The first option of each question worth the given points."""
    return [
        next(i for i, option in enumerate(q.options) if option.points == wanted)
        for q, wanted in zip(QUIZ.questions, points, strict=True)
    ]


def level_of(points: list[int]) -> str | None:
    result = QUIZ.grade(choose(points))
    return result.level if result else None


def test_the_document_has_five_questions_of_three_options() -> None:
    assert [len(q.options) for q in QUIZ.questions] == [3] * 5
    assert {"level1", "level1_plus", "level2"} == LEVELS


@pytest.mark.parametrize(
    ("points", "level"),
    [
        ([0, 0, 0, 0, 0], "level1"),  # 0
        ([2, 2, 0, 0, 0], "level1"),  # 4
        ([2, 2, 1, 0, 0], "level1_plus"),  # 5
        ([2, 2, 2, 1, 0], "level1_plus"),  # 7
        ([2, 2, 2, 2, 0], "level2"),  # 8
        ([2, 2, 2, 2, 2], "level2"),  # 10
        ([1, 1, 1, 1, 1], "level1_plus"),  # 5
    ],
)
def test_levels_by_sum(points: list[int], level: str) -> None:
    assert level_of(points) == level


def test_every_sum_from_0_to_10_has_a_level() -> None:
    for total in range(11):
        points = [min(2, max(0, total - 2 * i)) for i in range(5)]
        assert sum(points) == total
        assert level_of(points) is not None


@pytest.mark.parametrize(
    "choices",
    [[], [0, 0, 0, 0], [0, 0, 0, 0, 0, 0], [0, 0, None, 0, 0], [0, 0, 3, 0, 0], [0, 0, -1, 0, 0]],
)
def test_incomplete_or_spoiled_choices_have_no_result(choices: list[int | None]) -> None:
    assert QUIZ.grade(choices) is None


def test_the_texts_are_those_of_the_document(tmp_path: Path) -> None:
    expected = oracle()[1]

    assert [(r.level, r.name, r.advice, r.low, r.high) for r in QUIZ.results] == [
        (r.level, r.name, r.advice, r.low, r.high) for r in expected
    ]
