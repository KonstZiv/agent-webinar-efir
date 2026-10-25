"""The personal link of a registered visitor and the number of people who came by it."""

from collections.abc import Callable
from dataclasses import dataclass

from app.core.ports import ParticipantStore, StorageConflict
from app.core.referral.code import new_code
from app.core.referral.ports import ReferralStore

CODE_ATTEMPTS = 3  # a taken code is a one-in-2**48 event: a few tries are plenty


@dataclass(frozen=True, slots=True)
class Referral:
    """What the success screen shows: the code and the number, never other people's data."""

    code: str
    referred: int


class Referrals:
    def __init__(
        self,
        participants: ParticipantStore,
        store: ReferralStore,
        make_code: Callable[[], str] = new_code,
    ) -> None:
        self._participants = participants
        self._store = store
        self._make_code = make_code

    def for_address(self, email: str) -> Referral | None:
        """The code (made now if the participant has none) and the count; ``None`` if unknown."""
        participant = self._participants.by_email(email)
        if participant is None:
            return None
        code = participant.ref_code or self._code_for(participant.id)
        if code is None:
            return None
        return Referral(code, self._store.count_referred(participant.id))

    def _code_for(self, participant_id: int) -> str | None:
        for attempt in range(CODE_ATTEMPTS):
            try:
                return self._store.ensure_code(participant_id, self._make_code())
            except StorageConflict:
                if attempt == CODE_ATTEMPTS - 1:
                    raise
        return None
