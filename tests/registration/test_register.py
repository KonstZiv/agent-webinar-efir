"""``POST /register`` and ``GET /register`` (requirements, sections 3, 5, 6, 7 and 9).

An htmx request gets the new ``section#register``: the form with errors or the success screen;
a plain post without JavaScript gets the whole page of ``/``. A new and a known address get
the same answer; the invitation goes out in the background, once per participant. Runs on the
test database with fake Turnstile and Resend; ported from v1's tests/web/test_register.py and
extended with the allowlist, the bot links and the modes.
"""

import logging
import re
from typing import Any

import httpx
import pytest
from jinja2 import ChoiceLoader, DictLoader
from sqlalchemy import Engine

from app.adapters.db.participants import SqlParticipantStore
from app.adapters.registration.emails import SqlInvitationStore
from app.adapters.registration.keys import INVITATION, INVITATION_STORE
from app.core.entities import NewParticipant, Participant
from app.core.ports import StorageUnavailable
from app.core.registration.bot_links import TOKEN_TERM
from app.core.registration.invitation import InvitationDelivery
from app.core.unsubscribe import make_token
from app.services import LINK_TOKENS, PARTICIPANTS, override
from tests import copy_oracle as copy
from tests.conftest import BOT_ENV, REQUIRED_ENV, ParticipantFactory
from tests.fakes import FAILED, WEBINAR_START, FakeEmailSender, FakeHumanCheck
from tests.html_tree import normalize
from tests.registration.conftest import SiteFactory
from tests.registration.delivery import World
from tests.registration.helpers import (
    BOT,
    EMAIL,
    NO_MAIL,
    VALID,
    Conflicting,
    Failing,
    FakeMailDomains,
    Site,
    Unavailable,
    age_emails,
    app_log,
    page,
)

ERRORS = copy.table(copy.group(copy.section("1.8"), "Повідомлення про помилки"))
EMPTY = ERRORS["Поле пошти порожнє"]
INVALID = ERRORS["Адреса має неправильний формат"]
NO_MAIL_DOMAIN = ERRORS["Домен адреси не приймає пошту"]
NO_CONSENT = ERRORS["Позначку згоди не встановлено"]
NOT_HUMAN = ERRORS["Перевірку, що форму заповнює людина, не пройдено"]
TOO_MANY = ERRORS["Забагато спроб поспіль"]
SERVER = ERRORS["Помилка мережі або сервера"]
SCREEN = copy.section("2")
LIVE, REPLAY = copy.group(SCREEN, "live"), copy.group(SCREEN, "replay")
NOT_ALLOWED = copy.group(SCREEN, "Адреса не зі списку дозволених")
REPLAY_ENV = {"SITE_MODE": "replay", "RECORDING_YOUTUBE_ID": "Rec0rding_ID"}
ADMIN = {"Authorization": f"Bearer {REQUIRED_ENV['ADMIN_TOKEN']}"}
BOT_LINK = re.compile(rf"https://t\.me/{BOT}\?start=([A-Za-z0-9_-]+)")


def visible(response: httpx.Response) -> str:
    return page(response).text()


def screen_tokens(site: Site) -> list[str]:
    return [token.token for token in site.link_tokens() if token.source == "screen"]


# --- the success screen ----------------------------------------------------------------------


def test_new_participant_sees_the_success_fragment(site: Site) -> None:
    response = site.register()

    assert response.status_code == 200
    assert "<html" not in response.text  # a fragment for #register, not a page
    html = page(response)
    section = html.find("section", id="register")
    assert section.find("h2").text() == copy.one(LIVE, "Заголовок")
    text = section.text()
    for line in copy.labeled(LIVE, "Текст"):
        assert line.replace("{email}", EMAIL) in text
    assert copy.one(LIVE, "Підказка") in text
    assert [node for node in html.iter() if "data-lead" in node.attrs]
    assert "Visitor@Example.com" not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert "HX-Request" in response.headers["vary"]
    assert "<script" not in response.text


def test_the_participant_is_stored_by_v2_with_consent(site: Site) -> None:
    site.register()

    [participant] = site.participants()
    assert participant.email == EMAIL
    assert participant.origin == "v2"
    assert (participant.consent_version, participant.consent_at) == ("consent-v1", WEBINAR_START)
    assert participant.registered_at == WEBINAR_START
    assert site.human_check.tokens == ["tok"]


def test_a_new_and_a_known_address_get_the_same_answer(site: Site) -> None:
    first = site.register()
    second = site.register({**VALID, "email": "VISITOR@example.com"})

    assert first.status_code == second.status_code == 200
    assert second.text == first.text
    assert len(site.participants()) == 1


def test_the_same_answer_with_a_bot_differs_only_in_the_fresh_token(
    site_factory: SiteFactory,
) -> None:
    site = site_factory(**BOT_ENV)

    first = site.register()
    second = site.register()

    assert first.text != second.text  # a new token on every screen
    assert BOT_LINK.sub("TOKEN", first.text) == BOT_LINK.sub("TOKEN", second.text)
    assert len(site.participants()) == 1


def test_a_repeated_registration_keeps_the_first_source_and_consent(site: Site) -> None:
    site.client.get("/?utm_source=first")
    site.register()
    site.clock.advance(TOKEN_TERM)
    site.client.cookies.clear()
    site.client.get("/?utm_source=second")

    site.register()

    [participant] = site.participants()
    assert (participant.utm_source, participant.consent_at, participant.registered_at) == (
        "first",
        WEBINAR_START,
        WEBINAR_START,
    )


def test_replay_shows_the_recording_to_those_who_registered(site_factory: SiteFactory) -> None:
    site = site_factory(**REPLAY_ENV)

    response = site.register()

    section = page(response).find("section", id="register")
    assert section.find("h2").text() == copy.one(REPLAY, "Заголовок")
    [player] = section.find_all("iframe")
    assert player.attrs["src"] == "https://www.youtube-nocookie.com/embed/Rec0rding_ID"
    for line in copy.labeled(REPLAY, "Текст"):
        assert line.replace("{email}", EMAIL) in section.text()
    again = site.register()
    assert again.text == response.text  # the same address opens the player again


def test_live_has_no_player(site: Site) -> None:
    assert page(site.register()).find_all("iframe") == []


def test_the_bot_button_carries_a_fresh_screen_token(site_factory: SiteFactory) -> None:
    site = site_factory(**BOT_ENV)
    bot = copy.group(SCREEN, "Бот")

    first = page(site.register())
    second = page(site.register())

    [link] = [a for a in first.find_all("a") if a.text() == copy.one(bot, "Кнопка")]
    found = BOT_LINK.fullmatch(link.attrs["href"] or "")
    assert found is not None
    assert copy.one(bot, "Заголовок") in first.text()
    assert copy.one(bot, "Текст") in first.text()
    tokens = screen_tokens(site)
    assert tokens[0] == found.group(1)
    assert len(tokens) == 2 and tokens[0] != tokens[1]
    [again] = [a for a in second.find_all("a") if a.text() == copy.one(bot, "Кнопка")]
    assert again.attrs["href"] == f"https://t.me/{BOT}?start={tokens[1]}"
    [token] = [row for row in site.link_tokens() if row.token == tokens[0]]
    [participant] = site.participants()
    assert (token.participant_id, token.created_at, token.expires_at) == (
        participant.id,
        WEBINAR_START,
        WEBINAR_START + TOKEN_TERM,
    )
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token.token)


def test_without_a_bot_the_screen_shows_text_and_no_token_is_issued(site: Site) -> None:
    no_bot = copy.group(SCREEN, "Без бота")

    response = site.register()

    section = page(response).find("section", id="register")
    assert copy.one(no_bot, "Текст") in section.text()
    assert "t.me/agentic_engineers" in response.text
    assert "?start=" not in response.text
    assert site.link_tokens() == []


def test_partials_of_features_are_included_by_name(site_factory: SiteFactory) -> None:
    site = site_factory()
    env = site.client.app.state.container.templates.env  # type: ignore[attr-defined]
    partials = {"_referral.html": "<p>REFERRAL</p>", "_quiz.html": "<p>QUIZ</p>"}
    env.loader = ChoiceLoader([DictLoader(partials), env.loader])

    shown = visible(site.register())

    assert "REFERRAL" in shown and "QUIZ" in shown


def test_without_the_partials_of_features_the_screen_works(site: Site) -> None:
    response = site.register()

    assert response.status_code == 200
    assert "REFERRAL" not in response.text


# --- the form with errors --------------------------------------------------------------------


def test_all_field_errors_come_together(site: Site) -> None:
    response = site.register({"email": "  ", "cf-turnstile-response": "tok"})

    assert response.status_code == 422
    text = visible(response)
    assert EMPTY in text
    assert NO_CONSENT in text
    assert NOT_HUMAN not in text
    assert site.human_check.tokens == []
    assert site.participants() == []
    form = page(response).find("form")
    assert form.attrs["hx-post"] == "/register"
    assert form.find("input", name="email").attrs["aria-invalid"] == "true"
    assert form.find("input", name="consent").attrs["aria-invalid"] == "true"
    assert "<script" not in response.text  # the page has them already
    assert not [node for node in page(response).iter() if "data-lead" in node.attrs]


def test_invalid_address_keeps_what_was_typed(site: Site) -> None:
    response = site.register({**VALID, "email": "name@example"})

    assert response.status_code == 422
    assert INVALID in visible(response)
    assert EMPTY not in visible(response)
    form = page(response).find("form")
    assert form.find("input", name="email").attrs["value"] == "name@example"
    assert "checked" in form.find("input", name="consent").attrs
    assert site.participants() == []


def test_a_domain_that_takes_no_mail_is_refused_and_nothing_is_saved(
    site_factory: SiteFactory,
) -> None:
    site = site_factory(mail_domains=FakeMailDomains([NO_MAIL]))

    response = site.register({**VALID, "email": f"Visitor@{NO_MAIL}"})

    assert response.status_code == 422
    form = page(response).find("form")
    assert normalize(form.find("span", id="email-error").text()) == NO_MAIL_DOMAIN
    email = form.find("input", name="email")
    assert email.attrs["aria-invalid"] == "true"
    assert email.attrs["value"] == f"Visitor@{NO_MAIL}"
    assert INVALID not in visible(response)
    assert site.mail_domains.asked == [NO_MAIL]
    assert site.participants() == []
    assert site.emails() == []
    assert site.email_sender.sent == []


def test_a_domain_that_takes_mail_registers(site: Site) -> None:
    response = site.register()

    assert response.status_code == 200
    assert site.mail_domains.asked == ["example.com"]
    assert [participant.email for participant in site.participants()] == [EMAIL]


def test_without_htmx_the_page_shows_the_domain_problem(site_factory: SiteFactory) -> None:
    site = site_factory(mail_domains=FakeMailDomains([NO_MAIL]))

    response = site.register({**VALID, "email": f"visitor@{NO_MAIL}"}, htmx=False)

    assert response.status_code == 422
    assert NO_MAIL_DOMAIN in page(response).find(id="register").text()


@pytest.mark.parametrize("consent", [None, "", "on"])
def test_without_consent_nothing_is_saved(site: Site, consent: str | None) -> None:
    data = {key: value for key, value in VALID.items() if key != "consent"}
    if consent is not None:
        data["consent"] = consent

    response = site.register(data)

    assert response.status_code == 422
    assert NO_CONSENT in visible(response)
    assert "checked" not in page(response).find("input", name="consent").attrs
    assert site.participants() == []


def test_failed_turnstile(site_factory: SiteFactory) -> None:
    site = site_factory(human_check=FakeHumanCheck(success=False))

    response = site.register({**VALID, "cf-turnstile-response": ""})

    assert response.status_code == 422
    assert NOT_HUMAN in visible(response)
    assert site.participants() == []


def test_hostname_outside_the_list(site_factory: SiteFactory) -> None:
    allowed = "agent.pythoncourse.me"
    foreign = site_factory(
        human_check=FakeHumanCheck(hostname="evil.example.net"),
        TURNSTILE_ALLOWED_HOSTNAMES=allowed,
    )

    response = foreign.register()

    assert response.status_code == 422
    assert NOT_HUMAN in visible(response)
    assert foreign.participants() == []
    own = site_factory(
        human_check=FakeHumanCheck(hostname=allowed), TURNSTILE_ALLOWED_HOSTNAMES=allowed
    )
    assert own.register().status_code == 200


def test_turnstile_unavailable_is_a_server_error(site_factory: SiteFactory) -> None:
    site = site_factory(human_check=FakeHumanCheck(unavailable=True))

    response = site.register()

    assert response.status_code == 503
    [alert] = [node for node in page(response).iter() if "data-network-error" in node.attrs]
    assert normalize(alert.text()) == SERVER
    assert "hidden" not in alert.attrs
    assert site.participants() == []


def test_a_database_outage_is_a_server_error(site_factory: SiteFactory) -> None:
    site = site_factory(overrides=[override(PARTICIPANTS, Unavailable())])

    response = site.register()

    assert response.status_code == 503
    assert SERVER in visible(response)
    assert "StorageUnavailable" not in response.text


# --- limits of attempts ------------------------------------------------------------------------


def exhaust(site: Site, headers: dict[str, str] | None = None) -> None:
    for _ in range(30):
        assert site.register({}, headers=headers).status_code == 422


def test_too_many_attempts_from_one_address(site: Site) -> None:
    exhaust(site, {"X-Real-IP": "192.0.2.10"})

    response = site.register(headers={"X-Real-IP": "192.0.2.10"})

    assert response.status_code == 429
    assert TOO_MANY in visible(response)
    assert site.human_check.tokens == []
    assert site.participants() == []


def test_two_client_addresses_have_separate_limits(site: Site) -> None:
    exhaust(site, {"X-Real-IP": "192.0.2.10"})

    assert site.register(headers={"X-Real-IP": "198.51.100.20"}).status_code == 200


def test_forged_forwarded_for_does_not_reset_the_limit(site: Site) -> None:
    for index in range(30):
        headers = {"X-Real-IP": "192.0.2.10", "X-Forwarded-For": f"203.0.113.{index}"}
        assert site.register({}, headers=headers).status_code == 422

    response = site.register(headers={"X-Real-IP": "192.0.2.10", "X-Forwarded-For": "203.0.113.99"})

    assert response.status_code == 429


def test_without_real_ip_the_connection_address_counts(site: Site) -> None:
    exhaust(site)

    assert site.register().status_code == 429
    assert site.register(headers={"X-Real-IP": "not-an-ip"}).status_code == 429


def test_too_many_attempts_for_one_address(site: Site) -> None:
    for _ in range(5):
        assert site.register().status_code == 200

    response = site.register({**VALID, "email": "visitor@EXAMPLE.com"})

    assert response.status_code == 429
    assert TOO_MANY in visible(response)


# --- the allowlist of the staging site -------------------------------------------------------


@pytest.fixture
def staging(site_factory: SiteFactory) -> Site:
    return site_factory(REGISTRATION_ALLOWLIST="tester@example.com")


def test_an_address_off_the_allowlist_sees_the_notice_and_nothing_is_stored(
    staging: Site,
) -> None:
    response = staging.register()

    assert response.status_code == 200
    section = page(response).find("section", id="register")
    assert section.find("h2").text() == copy.one(NOT_ALLOWED, "Заголовок")
    assert copy.one(NOT_ALLOWED, "Текст") in section.text()
    [link] = section.find_all("a")
    assert link.text() == copy.one(NOT_ALLOWED, "Посилання")
    assert link.attrs["href"] == (
        "https://agent.pythoncourse.me/?utm_source=staging&utm_medium=referral&utm_content=notice"
    )
    assert not [node for node in page(response).iter() if "data-lead" in node.attrs]
    assert staging.participants() == []
    assert staging.emails() == []
    assert staging.email_sender.sent == []


def test_addresses_on_the_allowlist_register_again_and_again(staging: Site) -> None:
    answers = [
        staging.register({**VALID, "email": "tester+rehearsal@example.com"}).status_code
        for _ in range(7)
    ] + [staging.register({**VALID, "email": "tester@example.com"}).status_code for _ in range(7)]

    assert set(answers) == {200}
    assert sorted(p.email for p in staging.participants()) == [
        "tester+rehearsal@example.com",
        "tester@example.com",
    ]
    assert len(staging.email_sender.sent) == 2


# --- the invitation ----------------------------------------------------------------------------


def test_the_invitation_goes_out_once(site: Site) -> None:
    site.register()
    site.register()

    [(message, _)] = site.email_sender.sent
    assert message.to == EMAIL
    [record] = site.emails()
    assert (record.kind, record.status) == ("lesson_invitation", "sent")


def test_a_failure_of_resend_does_not_break_the_registration(site_factory: SiteFactory) -> None:
    site = site_factory(email_sender=FakeEmailSender(FAILED))

    response = site.register()

    assert response.status_code == 200
    [record] = site.emails()
    assert (record.status, record.last_error) == ("failed", FAILED.error)


def test_a_repeated_registration_resends_only_a_failed_invitation(
    site_factory: SiteFactory,
) -> None:
    site = site_factory(email_sender=FakeEmailSender(FAILED))
    site.register()

    site.register()
    site.register()

    assert len(site.email_sender.sent) == 2
    [record] = site.emails()
    assert (record.status, record.attempts) == ("sent", FAILED.attempts + 1)


def test_a_participant_of_v1_gets_the_screen_and_one_invitation(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant_factory(EMAIL, origin=None, emails={"confirmation": "sent"})

    first = site.register()
    second = site.register()

    assert first.status_code == second.status_code == 200
    assert copy.one(LIVE, "Заголовок") in visible(first)
    [participant] = site.participants()
    assert participant.origin is None  # the row of v1 stays as it was
    assert [message.to for message, _ in site.email_sender.sent] == [EMAIL]
    assert sorted((row.kind, row.status) for row in site.emails()) == [
        ("confirmation", "sent"),
        ("lesson_invitation", "sent"),
    ]


class LostAcknowledgement:
    """The first ``add_if_absent`` commits, then the connection drops before the answer."""

    def __init__(self, store: SqlParticipantStore) -> None:
        self.store = store
        self.lost = False

    def add_if_absent(self, participant: NewParticipant) -> tuple[Participant, bool]:
        result = self.store.add_if_absent(participant)
        if not self.lost:
            self.lost = True
            raise StorageUnavailable("add participant")
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self.store, name)


def test_a_repeat_after_a_lost_commit_acknowledgement_sends_one_invitation(
    site_factory: SiteFactory, migrated_engine: Engine
) -> None:
    """The participant was stored, the visitor saw 503 and tried again: one invitation."""
    store = LostAcknowledgement(SqlParticipantStore(migrated_engine))
    site = site_factory(overrides=[override(PARTICIPANTS, store)])

    lost = site.register()
    repeated = site.register()
    again = site.register()

    assert lost.status_code == 503
    assert repeated.status_code == again.status_code == 200
    assert len(site.participants()) == 1
    assert len(site.email_sender.sent) == 1


class StopsAfterTheAnswer:
    """The invitation's scenario whose background work never runs: the process stopped."""

    def __init__(self, delivery: InvitationDelivery) -> None:
        self.delivery = delivery

    def deliver(self, *args: object) -> None:
        """The process stopped right after the answer, before the background did anything."""

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delivery, name)


def test_the_invitation_is_recorded_before_the_answer(
    site_factory: SiteFactory, migrated_engine: Engine
) -> None:
    """Whatever stops the background, the «pending» row becomes a failure the retry resends."""
    world = World(migrated_engine, bot="")
    site = site_factory(
        email_sender=world.sender,
        clock=world.clock,
        overrides=[override(INVITATION, StopsAfterTheAnswer(world.delivery()))],
    )

    response = site.register()

    assert response.status_code == 200
    [record] = site.emails()
    assert (record.kind, record.status, record.attempts) == ("lesson_invitation", "pending", 0)
    assert world.sender.sent == []
    age_emails(migrated_engine, 16)
    retried = site.client.post("/admin/emails/retry", headers=ADMIN)
    assert retried.json() == {"attempted": 1, "sent": 1, "failed": 0}
    assert [message.to for message, _ in world.sender.sent] == [EMAIL]


class Breakable:
    """A store that raises ``StorageUnavailable`` while ``broken``; otherwise the real one."""

    def __init__(self, store: object) -> None:
        self.store = store
        self.broken = False

    def __getattr__(self, name: str) -> Any:
        if self.broken:
            return getattr(Unavailable(), name)
        return getattr(self.store, name)


def test_an_invitation_that_cannot_be_recorded_is_a_server_error(
    site_factory: SiteFactory, migrated_engine: Engine
) -> None:
    """Registered, but no invitation would go out: the visitor tries again and gets it."""
    store = Breakable(SqlInvitationStore(migrated_engine))
    site = site_factory(overrides=[override(INVITATION_STORE, store)])
    store.broken = True

    failed = site.register()
    store.broken = False
    repeated = site.register()

    assert failed.status_code == 503
    assert SERVER in visible(failed)
    assert repeated.status_code == 200
    assert copy.one(LIVE, "Заголовок") in visible(repeated)
    assert len(site.participants()) == 1
    assert [message.to for message, _ in site.email_sender.sent] == [EMAIL]


def test_an_invitation_that_cannot_be_recorded_gives_the_attempt_back(
    site_factory: SiteFactory, migrated_engine: Engine
) -> None:
    """As in v1, a storage failure does not use up the attempts for the address."""
    store = Breakable(SqlInvitationStore(migrated_engine))
    site = site_factory(overrides=[override(INVITATION_STORE, store)])
    store.broken = True

    failed = [site.register().status_code for _ in range(7)]
    store.broken = False
    repeated = site.register()

    assert failed == [503] * 7
    assert repeated.status_code == 200
    assert [message.to for message, _ in site.email_sender.sent] == [EMAIL]


@pytest.mark.parametrize(
    ("store", "error"),
    [
        (Unavailable, "StorageUnavailable"),
        (Conflicting, "StorageConflict"),
        (Failing, "StorageError"),
    ],
    ids=["unavailable", "conflict", "other"],
)
def test_a_screen_token_that_cannot_be_stored_leaves_the_screen_without_the_bot(
    site_factory: SiteFactory, caplog: pytest.LogCaptureFixture, store: type, error: str
) -> None:
    """Registered, the invitation is on its way with its own link: no error, no button.

    Any storage failure, a bug included: the visitor is registered either way. The log says
    so at the level of an error, with the class only.
    """
    site = site_factory(overrides=[override(LINK_TOKENS, store())], **BOT_ENV)
    no_bot = copy.group(SCREEN, "Без бота")

    response = site.register()

    assert response.status_code == 200
    section = page(response).find("section", id="register")
    assert section.find("h2").text() == copy.one(LIVE, "Заголовок")
    assert copy.one(no_bot, "Текст") in section.text()
    assert "?start=" not in response.text
    assert SERVER not in visible(response)
    assert len(site.participants()) == 1
    assert [record.kind for record in site.emails()] == ["lesson_invitation"]
    [logged] = [
        record
        for record in caplog.records
        if record.getMessage() == f"Success screen: no link to the bot: {error}"
    ]
    assert logged.levelno == logging.ERROR


# --- without JavaScript -------------------------------------------------------------------------


def test_without_htmx_the_whole_page_comes_back(site: Site) -> None:
    errors = site.register({"email": "name@"}, htmx=False)
    success = site.register(htmx=False)

    assert errors.status_code == 422
    html = page(errors)
    assert html.find("html").attrs["lang"] == "uk"
    assert INVALID in html.find(id="register").text()
    assert html.find("title").text_raw()  # the page of / with its service tags
    assert success.status_code == 200
    register = page(success).find(id="register")
    assert register.find("h2").text() == copy.one(LIVE, "Заголовок")
    assert [node for node in page(success).iter() if "data-lead" in node.attrs]


def test_without_htmx_the_landing_is_used_once_it_exists(site: Site) -> None:
    env = site.client.app.state.container.templates.env  # type: ignore[attr-defined]
    landing = (
        '{% extends "base.html" %}{% block main %}<h1>LANDING</h1>'
        '{% include "_form.html" ignore missing %}{% endblock %}'
    )
    env.loader = ChoiceLoader([DictLoader({"landing.html": landing}), env.loader])

    response = site.register(htmx=False)

    html = page(response)
    assert html.find("h1").text() == "LANDING"
    assert html.find(id="register").find("h2").text() == copy.one(LIVE, "Заголовок")


def test_get_register_leads_to_the_form(site: Site) -> None:
    response = site.client.get("/register", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/#register"


# --- what reaches the participant's row and the log ------------------------------------------


def test_source_cookie_reaches_the_participant(site: Site) -> None:
    site.client.get(
        "/?utm_source=telegram&utm_campaign=webinar&gclid=abc",
        headers={"Referer": "https://t.me/agentic_engineers"},
    )

    site.register()

    [participant] = site.participants()
    assert participant.utm_source == "telegram"
    assert participant.utm_campaign == "webinar"
    assert participant.gclid == "abc"
    assert (
        participant.landing_url
        == "https://testserver/?utm_source=telegram&utm_campaign=webinar&gclid=abc"
    )
    assert participant.referrer == "https://t.me/agentic_engineers"


def test_damaged_source_cookie_is_ignored(site: Site) -> None:
    site.client.cookies.set("src", "%%%not-base64%%%")

    assert site.register().status_code == 200
    [participant] = site.participants()
    assert (participant.utm_source, participant.landing_url) == (None, None)


@pytest.mark.parametrize(
    ("value", "stored"), [("123.456", "123.456"), ("<script>", None), ("1" * 120 + ".1", None)]
)
def test_ga_client_id(site: Site, value: str, stored: str | None) -> None:
    site.register({**VALID, "ga_client_id": value})

    [participant] = site.participants()
    assert participant.ga_client_id == stored


def test_log_has_only_masked_addresses_and_no_tokens(
    site_factory: SiteFactory, caplog: pytest.LogCaptureFixture
) -> None:
    site = site_factory(**BOT_ENV)
    caplog.set_level(logging.DEBUG)

    site.register({**VALID, "email": "Secret.Person@Example.com"})
    site.register({**VALID, "email": "secret.person@example.com"})
    site.register({**VALID, "email": "secret.person@example", "consent": ""})

    logged = app_log(caplog)
    assert "secret.person" not in logged.lower()
    assert "s***@example.com" in logged
    for token in site.link_tokens():
        assert token.token not in logged
    [participant] = site.participants()
    unsubscribe = make_token(participant.unsubscribe_id, REQUIRED_ENV["UNSUBSCRIBE_SECRET"])
    assert unsubscribe.split(".")[1] not in logged
