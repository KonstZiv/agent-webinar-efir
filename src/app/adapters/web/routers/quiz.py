"""``POST /quiz``: the answer of the level quiz (docs/requirements.md, section 4).

An htmx request gets the new ``div#quiz``: the result in place of the form, or the form again
with the problem. A plain post without JavaScript gets a small page with the same block, and
its form leads to the anchor of the result. The answer is accepted only with the ticket that
the success screen put in the form; a bad ticket, a bad answer and a storage failure write
nothing. Never cached or indexed; the log carries no address, ticket or answer.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from app.adapters.quiz.keys import QUIZ
from app.adapters.quiz.view import QuizState
from app.adapters.web.dependencies import ContainerDep, service
from app.adapters.web.headers import SERVICE
from app.core.quiz.service import Answered, LevelQuiz, Problem

router = APIRouter()

FRAGMENT = "_quiz.html"
PAGE = "quiz.html"
_STATUS = {Problem.INCOMPLETE: 422, Problem.EXPIRED: 422, Problem.NOT_SAVED: 503}
_HEADERS = {**SERVICE, "Vary": "HX-Request"}

QuizDep = Annotated[LevelQuiz, Depends(service(QUIZ))]


def _choice(value: str) -> int | None:
    return int(value) if value.isascii() and value.isdigit() and len(value) < 3 else None


@router.post("/quiz", response_class=HTMLResponse)
def answer_quiz(
    request: Request,
    container: ContainerDep,
    quiz: QuizDep,
    ticket: Annotated[str, Form()] = "",
    q1: Annotated[str, Form()] = "",
    q2: Annotated[str, Form()] = "",
    q3: Annotated[str, Form()] = "",
    q4: Annotated[str, Form()] = "",
    q5: Annotated[str, Form()] = "",
) -> HTMLResponse:
    choices = [_choice(value) for value in (q1, q2, q3, q4, q5)]
    outcome = quiz.answer(ticket, choices)
    chosen = {
        number: choice for number, choice in enumerate(choices, start=1) if choice is not None
    }
    if isinstance(outcome, Answered):
        state, status = QuizState(result=outcome.result), 200
    else:
        problem = outcome.problem
        state = QuizState(ticket=ticket, chosen=chosen, problem=problem.value)
        status = _STATUS[problem]
    template = FRAGMENT if request.headers.get("HX-Request") == "true" else PAGE
    context: dict[str, object] = {"quiz_state": state, "noindex": True}
    return container.templates.TemplateResponse(
        request, template, context, status_code=status, headers=_HEADERS
    )
