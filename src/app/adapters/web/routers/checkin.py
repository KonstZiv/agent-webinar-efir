"""``GET`` and ``POST /checkin``: a registered participant marks the lesson (requirements, 9а).

``GET`` is the page with the form; ``?code=`` (the link of the post and of the chat of the lesson)
fills in the code, when it is one, and puts the cursor on the address. An htmx ``POST`` gets the
new ``div#checkin``: the success in place of the form, or the form again with the problem. A
plain post without JavaScript gets the whole page with the same block (as ``/quiz``). Never
cached or indexed; the log carries no address, code or question.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from app.adapters.checkin.keys import ATTENDANCE, TEXTS
from app.adapters.checkin.view import CheckinState
from app.adapters.web.client_ip import client_ip
from app.adapters.web.dependencies import Container, ContainerDep, service
from app.adapters.web.headers import SERVICE
from app.core.checkin.model import CODE_ALPHABET, CODE_LENGTH, normalize_code
from app.core.checkin.service import Attendance, Marked, Problem

router = APIRouter()

FRAGMENT = "_checkin.html"
PAGE = "checkin.html"
_STATUS = {
    Problem.TOO_MANY: 429,
    Problem.FAILED: 503,
}
UNPROCESSABLE = 422
_HEADERS = {**SERVICE, "Vary": "HX-Request"}

AttendanceDep = Annotated[Attendance, Depends(service(ATTENDANCE))]


def _render(
    request: Request, container: Container, state: CheckinState, status: int
) -> HTMLResponse:
    template = FRAGMENT if request.headers.get("HX-Request") == "true" else PAGE
    context: dict[str, object] = {"checkin_state": state, "noindex": True}
    return container.templates.TemplateResponse(
        request, template, context, status_code=status, headers=_HEADERS
    )


def _prefilled(code: str) -> CheckinState:
    """The form with the code of a link (the post, the chat of the lesson), if it is a code.

    Anything else, including a code of the wrong length or outside the alphabet, is not echoed:
    the field stays empty. The cursor goes to the address, which is all that is left to type.
    """
    wanted = normalize_code(code)
    if len(wanted) == CODE_LENGTH and set(wanted) <= set(CODE_ALPHABET):
        return CheckinState(code=wanted, autofocus_email=True)
    return CheckinState()


@router.get("/checkin", response_class=HTMLResponse)
def checkin_page(request: Request, container: ContainerDep, code: str = "") -> HTMLResponse:
    return _render(request, container, _prefilled(code), 200)


@router.post("/checkin", response_class=HTMLResponse)
def mark_attendance(
    request: Request,
    container: ContainerDep,
    attendance: AttendanceDep,
    code: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    rating: Annotated[str, Form()] = "",
    question: Annotated[str, Form()] = "",
) -> HTMLResponse:
    outcome = attendance.mark(client_ip(request), code, email, rating, question)
    if isinstance(outcome, Marked):
        texts = container.services.get(TEXTS)
        state = CheckinState(
            success=texts.success(outcome.checkin.lesson_date, outcome.email),
            feedback=outcome.feedback,
        )
        return _render(request, container, state, 200)
    state = CheckinState(
        code=code, email=email, rating=rating, question=question, problem=outcome.problem.value
    )
    return _render(request, container, state, _STATUS.get(outcome.problem, UNPROCESSABLE))
