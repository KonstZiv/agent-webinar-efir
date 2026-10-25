"""The feature Ф1 «реферальні посилання»: a personal link on the success screen.

``install`` provides the slice's services by key (``app.adapters.referral.keys``), adds the
middleware that remembers the code of the link in the cookie ``ref``, and gives
``_referral.html`` its values (template global ``referral``). The registration records the
inviter when it creates a participant; this slice makes the code and counts the people.
The texts (docs/copy.md, 12.1) are read at startup.
"""

from pathlib import Path

from app.adapters.referral.cookie import ReferralCookie
from app.adapters.referral.keys import REFERRALS, STORE
from app.adapters.referral.store import SqlReferralStore
from app.adapters.referral.texts import load_texts
from app.adapters.referral.view import ReferralPartial
from app.core.referral.service import Referrals
from app.services import PARTICIPANTS
from app.slices import SliceSetup

# Texts live in the repository's docs/; the working directory is the repository (as in main.py).
DOCS_DIR = Path("docs")


def install(setup: SliceSetup) -> None:
    services = setup.services
    texts = load_texts(DOCS_DIR)

    setup.provide(STORE, lambda: SqlReferralStore(setup.engine()))
    setup.provide(REFERRALS, lambda: Referrals(services.get(PARTICIPANTS), services.get(STORE)))
    setup.add_middleware(ReferralCookie)
    setup.template_global(
        "referral",
        ReferralPartial(
            texts=texts,
            base_url=setup.settings.public_base_url,
            lookup=lambda email: services.get(REFERRALS).for_address(email),
        ),
    )
