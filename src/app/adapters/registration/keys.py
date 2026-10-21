"""Services of the slice «реєстрація і лист» by key (``app.services``), named ``registration.*``.

The keys live here, not in ``app.slices.registration``: routes import them, and a route module
must import without the slice package (the foundation's tests swap ``app.slices`` for a sample).
"""

from app.adapters.registration.mail import MailWorkers
from app.core.registration.bot_links import BotLinks
from app.core.registration.invitation import InvitationDelivery
from app.core.registration.ports import InvitationStore, MailDomains
from app.core.registration.registration import Registration
from app.core.registration.unsubscription import Unsubscription
from app.services import Key

REGISTRATION = Key[Registration]("registration.registration")
UNSUBSCRIPTION = Key[Unsubscription]("registration.unsubscription")
INVITATION_STORE = Key[InvitationStore]("registration.invitation_store")
BOT_LINKS = Key[BotLinks]("registration.bot_links")
INVITATION = Key[InvitationDelivery]("registration.invitation")
MAIL_WORKERS = Key[MailWorkers]("registration.mail_workers")
MAIL_DOMAINS = Key[MailDomains]("registration.mail_domains")
