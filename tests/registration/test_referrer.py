"""The registration records the inviter (cookie ``ref``) when it creates a participant (Ф1)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.db.models import Participant
from tests.conftest import ParticipantFactory
from tests.registration.helpers import VALID, Site

CODE = "Inviter1"


def referred_by(site: Site, email: str) -> int | None:
    with Session(site.engine) as session:
        return session.scalars(
            select(Participant.referred_by).where(Participant.email == email)
        ).one()


def test_a_new_address_records_the_inviter(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    inviter = participant_factory(ref_code=CODE)

    site.client.cookies.set("ref", CODE)
    response = site.register({**VALID, "email": "new@example.com"})

    assert response.status_code == 200
    assert referred_by(site, "new@example.com") == inviter.id


def test_an_address_registered_earlier_is_not_counted(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant_factory(ref_code=CODE)
    participant_factory("registered@example.com")

    site.client.cookies.set("ref", CODE)
    response = site.register({**VALID, "email": "registered@example.com"})

    assert response.status_code == 200
    assert referred_by(site, "registered@example.com") is None


def test_the_second_registration_does_not_change_the_inviter(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    first = participant_factory(ref_code=CODE)
    participant_factory(ref_code="Another1")

    site.client.cookies.set("ref", CODE)
    site.register({**VALID, "email": "guest@example.com"})
    site.client.cookies.set("ref", "Another1")
    site.register({**VALID, "email": "guest@example.com"})

    assert referred_by(site, "guest@example.com") == first.id


def test_an_unknown_or_damaged_code_changes_nothing(site: Site) -> None:
    for number, code in enumerate(("Unknown1", "x" * 500, "a b")):
        site.client.cookies.set("ref", code)

        response = site.register({**VALID, "email": f"guest-{number}@example.com"})

        assert response.status_code == 200
        assert referred_by(site, f"guest-{number}@example.com") is None
