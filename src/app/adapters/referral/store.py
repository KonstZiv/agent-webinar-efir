"""``ReferralStore`` on the shared table ``participants``: ``ref_code`` and ``referred_by`` only."""

from sqlalchemy import Engine, func, select, update

from app.adapters.db.models import Participant
from app.adapters.db.transaction import transaction


class SqlReferralStore:
    """``ReferralStore`` backed by a SQLAlchemy engine."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def ensure_code(self, participant_id: int, candidate: str) -> str | None:
        claim = (
            update(Participant)
            .where(Participant.id == participant_id, Participant.ref_code.is_(None))
            .values(ref_code=candidate)
            .returning(Participant.ref_code)
        )
        with transaction(self._engine, "make referral code") as session:
            made = session.scalars(claim).first()
            if made is not None:
                return made
            # Already has one (or is gone); the code is never rewritten.
            return session.scalars(
                select(Participant.ref_code).where(Participant.id == participant_id)
            ).first()

    def count_referred(self, participant_id: int) -> int:
        statement = select(func.count()).where(Participant.referred_by == participant_id)
        with transaction(self._engine, "count referred") as session:
            return session.scalar(statement) or 0
