"""A participant with rows in every table of the shared model, for the tests of every slice.

``participant_factory`` (tests/conftest.py) binds ``add_participant`` to the migrated test
database. Addresses are ``…@example.com`` only; tokens are random, of the allowed characters.
"""

import secrets
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.adapters.db.models import Click, EmailRecord, LinkToken, Participant
from app.core.entities import ORIGIN_V2, LinkSource, TelegramAccount

LINK_TOKEN_TERM = timedelta(days=7)
REGISTERED_AT = datetime(2026, 10, 20, 16, 5, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class CreatedParticipant:
    id: int
    email: str
    unsubscribe_id: uuid.UUID
    link_tokens: tuple[str, ...] = ()


def add_participant(
    engine: Engine,
    email: str | None = None,
    *,
    origin: str | None = ORIGIN_V2,
    registered_at: datetime = REGISTERED_AT,
    telegram: TelegramAccount | None = None,
    channel_member: bool | None = None,
    level: str | None = None,
    ref_code: str | None = None,
    referred_by: int | None = None,
    emails: Mapping[str, str] | None = None,
    link_tokens: Sequence[LinkSource] = (),
    clicks: Sequence[str] = (),
) -> CreatedParticipant:
    """Store a participant (by default of v2) and, if asked, their rows in the other tables.

    ``emails`` maps a kind to a status (``{"lesson_invitation": "sent"}``); ``link_tokens``
    lists sources of tokens to issue now; ``clicks`` lists kinds (``lesson``, ``course``).
    ``origin=None`` makes a participant as v1 stores it.
    """
    address = email if email is not None else f"participant-{uuid.uuid4().hex[:12]}@example.com"
    tokens = tuple(secrets.token_urlsafe(32) for _ in link_tokens)
    with Session(engine) as session, session.begin():
        participant = Participant(
            email=address,
            unsubscribe_id=uuid.uuid4(),
            registered_at=registered_at,
            consent_version="consent-v1",
            consent_at=registered_at,
            origin=origin,
            tg_user_id=telegram.user_id if telegram else None,
            tg_username=telegram.username if telegram else None,
            tg_linked_at=registered_at if telegram else None,
            channel_member=channel_member,
            level=level,
            ref_code=ref_code,
            referred_by=referred_by,
        )
        session.add(participant)
        session.flush()
        for kind, status in (emails or {}).items():
            session.add(
                EmailRecord(
                    participant_id=participant.id,
                    kind=kind,
                    status=status,
                    idempotency_key=uuid.uuid4(),
                )
            )
        for token, source in zip(tokens, link_tokens, strict=True):
            session.add(
                LinkToken(
                    participant_id=participant.id,
                    token=token,
                    source=source,
                    created_at=registered_at,
                    expires_at=registered_at + LINK_TOKEN_TERM,
                )
            )
        for kind in clicks:
            session.add(Click(participant_id=participant.id, kind=kind, created_at=registered_at))
        created = CreatedParticipant(
            participant.id, participant.email, participant.unsubscribe_id, tokens
        )
    return created
