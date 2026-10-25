"""What ``_referral.html`` needs: the template global ``referral``.

Where the slice is not installed, the global is absent and the partial renders nothing. A storage
failure hides the part and never the success screen: the registration has happened.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from app.adapters.referral.texts import ReferralTexts
from app.core.ports import StorageError
from app.core.referral.service import Referral

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ReferralBlock:
    """The link and the line with the number: all the part shows of anyone."""

    link: str
    count_line: str


@dataclass(frozen=True, slots=True)
class ReferralPartial:
    texts: ReferralTexts
    base_url: str
    lookup: Callable[[str], Referral | None]

    def block_for(self, email: str) -> ReferralBlock | None:
        """The block of the participant with this address; ``None`` hides the part."""
        try:
            found = self.lookup(email)
        except StorageError as error:
            logger.error("Success screen: no referral link: %s", type(error).__name__)
            return None
        if found is None:
            return None
        link = f"{self.base_url}/?ref={found.code}"
        return ReferralBlock(link, self.texts.count_line(found.referred))
