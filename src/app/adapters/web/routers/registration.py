"""``POST /register`` and ``GET /register`` (docs/requirements.md, sections 4 and 5).

An htmx request gets the new ``section#register``: ``_form.html`` with the problems, or
``_success.html`` — the success screen of the mode, or the notice of the staging site. A plain
post without JavaScript gets the whole page of ``/`` (the landing once it exists), where the
partial shows the same. A new and a known address get the same screen. A registration records
the invitation as «pending» before the answer (a storage failure there is 503 and gives the
attempt for the address back: the visitor tries again and gets it); the letter goes out in the
background, once the answer has been sent, on the mail's own threads (``MailWorkers``), so slow
mail never holds the threads of the pages. Every success screen gets a fresh link to the bot, or
no button when the link cannot be stored.
``GET /register`` leads back to the form.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.adapters.registration.keys import BOT_LINKS, INVITATION, MAIL_WORKERS, REGISTRATION
from app.adapters.registration.mail import MailWorkers
from app.adapters.registration.source import SOURCE_COOKIE, decode_source
from app.adapters.registration.view import RegistrationState
from app.adapters.web.client_ip import client_ip
from app.adapters.web.dependencies import ContainerDep, service
from app.adapters.web.routers.home import FALLBACK, LANDING, has_template
from app.core.entities import Participant
from app.core.ports import StorageConflict, StorageError, StorageUnavailable
from app.core.registration.bot_links import BotLinks
from app.core.registration.invitation import InvitationDelivery
from app.core.registration.registration import (
    NotAllowed,
    Problem,
    Registered,
    Registration,
    RegistrationRequest,
    clean_ga_client_id,
)

logger = logging.getLogger(__name__)

router = APIRouter()

CONSENT_VALUE = "yes"  # the value of the consent checkbox in the form
REFERRAL_COOKIE = "ref"  # the code of an inviter's link (feature Ф1), set by the link's visit
FORM = "_form.html"
SCREEN = "_success.html"
_STATUS = {Problem.TOO_MANY_ATTEMPTS: 429, Problem.SERVICE_UNAVAILABLE: 503}
_HEADERS = {"Cache-Control": "no-store", "Vary": "HX-Request"}

RegistrationDep = Annotated[Registration, Depends(service(REGISTRATION))]
BotLinksDep = Annotated[BotLinks, Depends(service(BOT_LINKS))]
InvitationDep = Annotated[InvitationDelivery, Depends(service(INVITATION))]
MailWorkersDep = Annotated[MailWorkers, Depends(service(MAIL_WORKERS))]


def _refused(
    email: str, consent: bool, problems: tuple[Problem, ...]
) -> tuple[RegistrationState, int]:
    state = RegistrationState(
        email=email, consent=consent, problems=frozenset(problem.value for problem in problems)
    )
    return state, next((_STATUS[p] for p in problems if p in _STATUS), 422)


def _success_screen(participant: Participant, links: BotLinks) -> RegistrationState:
    """The screen of a registered visitor; without a stored ``screen`` token, no bot button.

    The registration has happened and the invitation (with its own link to the bot) is on its
    way, so any storage failure here — a bug included — shows the screen without the button,
    never an error; the log names the class only.
    """
    try:
        bot_url = links.issue(participant.id, "screen")
    except StorageError as error:
        logger.error("Success screen: no link to the bot: %s", type(error).__name__)
        bot_url = None
    return RegistrationState(email=participant.email, registered=True, bot_url=bot_url)


@router.post("/register", response_class=HTMLResponse)
def register(
    request: Request,
    container: ContainerDep,
    background_tasks: BackgroundTasks,
    registration: RegistrationDep,
    links: BotLinksDep,
    invitation: InvitationDep,
    workers: MailWorkersDep,
    email: Annotated[str, Form()] = "",
    consent: Annotated[str, Form()] = "",
    turnstile_token: Annotated[str, Form(alias="cf-turnstile-response")] = "",
    ga_client_id: Annotated[str, Form()] = "",
) -> HTMLResponse:
    given_consent = consent == CONSENT_VALUE
    outcome = registration.register(
        RegistrationRequest(
            email=email,
            consent=given_consent,
            human_token=turnstile_token,
            client_ip=client_ip(request),
            source=decode_source(request.cookies.get(SOURCE_COOKIE)),
            ga_client_id=clean_ga_client_id(ga_client_id),
            referrer_code=request.cookies.get(REFERRAL_COOKIE),
        )
    )
    if isinstance(outcome, Registered):
        participant = outcome.participant
        try:
            claimed = invitation.claim(participant.id)
        except (StorageUnavailable, StorageConflict) as error:
            logger.warning("Registration: invitation not recorded: %s", type(error).__name__)
            registration.give_back(email)
            state, status = _refused(email, given_consent, (Problem.SERVICE_UNAVAILABLE,))
        else:
            if claimed is not None:
                background_tasks.add_task(workers.run, invitation.deliver, claimed)
            state, status = _success_screen(participant, links), 200
    elif isinstance(outcome, NotAllowed):
        state, status = RegistrationState(not_allowed=True), 200
    else:
        state, status = _refused(email, given_consent, outcome.problems)

    mode = container.settings.site_mode
    context: dict[str, object] = {"site_mode": mode, "registration_state": state}
    if request.headers.get("HX-Request") == "true":
        template = SCREEN if state.screen else FORM
        context["form_fragment"] = True  # the page has the scripts of the form already
    else:
        template = LANDING if has_template(container.templates, LANDING) else FALLBACK
        context |= {
            "hero": container.page_texts.first_screen[mode],
            "page_meta": container.page_meta,
        }
    return container.templates.TemplateResponse(
        request, template, context, status_code=status, headers=_HEADERS
    )


@router.get("/register")
def register_page() -> RedirectResponse:
    """The address a form post without JavaScript leaves in the browser leads to the form."""
    return RedirectResponse("/#register", status_code=303)
