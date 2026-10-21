"""The slice «реєстрація і лист»: registration, the invitation, links from emails, unsubscribing.

``install`` provides the slice's services by key (``app.adapters.registration.keys``) and the
shared ports it owns, ``HUMAN_CHECK`` and ``EMAIL_SENDER``; adds the middleware of the cookie
``src`` and the values its partials need (template global ``registration``). Every service is
built on first use, so creating the application builds no client and reaches no network; the
client of Turnstile and the mail threads are closed when the application stops (Resend gets a
client per attempt). The check of the mail domain has one caching resolver of DNS for the
application (``MAIL_DOMAINS``).
"""

from app.adapters.ratelimit.memory import InMemoryRateLimiter
from app.adapters.registration.composer import JinjaInvitationComposer
from app.adapters.registration.emails import SqlInvitationStore
from app.adapters.registration.keys import (
    BOT_LINKS,
    INVITATION,
    INVITATION_STORE,
    MAIL_DOMAINS,
    MAIL_WORKERS,
    REGISTRATION,
    UNSUBSCRIPTION,
)
from app.adapters.registration.mail import MailWorkers
from app.adapters.registration.mail_domains import DnsMailDomains
from app.adapters.registration.resend import ResendEmailSender
from app.adapters.registration.settings import required
from app.adapters.registration.source import SourceCookie
from app.adapters.registration.view import FormSettings
from app.adapters.turnstile import cloudflare
from app.core.ports import EmailSender, HumanCheck
from app.core.registration.bot_links import BotLinks
from app.core.registration.invitation import InvitationDelivery
from app.core.registration.registration import ADDRESS_ATTEMPTS, IP_ATTEMPTS, Registration
from app.core.registration.unsubscription import Unsubscription
from app.services import CLOCK, EMAIL_SENDER, HUMAN_CHECK, LINK_TOKENS, PARTICIPANTS
from app.slices import SliceSetup


def install(setup: SliceSetup) -> None:
    settings = setup.settings
    services = setup.services
    unsubscribe_secret = required(
        settings.unsubscribe_secret, "UNSUBSCRIBE_SECRET"
    ).get_secret_value()

    def email_sender() -> EmailSender:
        return ResendEmailSender(
            required(settings.resend_api_key, "RESEND_API_KEY"),
            allowlist=settings.registration_allowlist,
        )

    def human_check() -> HumanCheck:
        client = cloudflare.make_http_client()
        setup.close_on_shutdown(client.close)
        return cloudflare.CloudflareTurnstile(
            required(settings.turnstile_secret_key, "TURNSTILE_SECRET_KEY"), client
        )

    def registration() -> Registration:
        clock = services.get(CLOCK)
        return Registration(
            participants=services.get(PARTICIPANTS),
            human_check=services.get(HUMAN_CHECK),
            ip_limiter=InMemoryRateLimiter(
                limit=IP_ATTEMPTS.limit, window=IP_ATTEMPTS.window, clock=clock
            ),
            address_limiter=InMemoryRateLimiter(
                limit=ADDRESS_ATTEMPTS.limit, window=ADDRESS_ATTEMPTS.window, clock=clock
            ),
            clock=clock,
            allowed_hostnames=settings.turnstile_allowed_hostnames,
            allowlist=settings.registration_allowlist,
            mail_domains=services.get(MAIL_DOMAINS),
        )

    def mail_workers() -> MailWorkers:
        workers = MailWorkers()
        setup.close_on_shutdown(workers.close)
        return workers

    setup.provide(HUMAN_CHECK, human_check)
    setup.provide(EMAIL_SENDER, email_sender)
    setup.provide(MAIL_DOMAINS, DnsMailDomains)
    setup.provide(REGISTRATION, registration)
    setup.provide(INVITATION_STORE, lambda: SqlInvitationStore(setup.engine()))
    setup.provide(MAIL_WORKERS, mail_workers)
    setup.provide(
        BOT_LINKS,
        lambda: BotLinks(
            tokens=services.get(LINK_TOKENS),
            clock=services.get(CLOCK),
            bot_username=settings.telegram_bot_username,
        ),
    )
    setup.provide(
        INVITATION,
        lambda: InvitationDelivery(
            store=services.get(INVITATION_STORE),
            sender=services.get(EMAIL_SENDER),
            composer=JinjaInvitationComposer(
                public_base_url=settings.public_base_url, sender_email=settings.sender_email
            ),
            links=services.get(BOT_LINKS),
            clock=services.get(CLOCK),
            unsubscribe_secret=unsubscribe_secret,
        ),
    )
    setup.provide(
        UNSUBSCRIPTION,
        lambda: Unsubscription(participants=services.get(PARTICIPANTS), secret=unsubscribe_secret),
    )
    setup.add_middleware(SourceCookie)
    setup.template_global(
        "registration",
        FormSettings(
            turnstile_site_key=settings.turnstile_site_key,
            recording_youtube_id=settings.recording_youtube_id,
        ),
    )
