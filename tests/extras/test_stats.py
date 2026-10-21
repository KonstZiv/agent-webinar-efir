"""``GET /admin/stats`` (docs/requirements.md, section 8; docs/contract.md, section 8).

JSON with v1's keys ``total``, ``last_24h``, ``failed_emails`` — the same values v1 gives on the
same database — and the new ``telegram_linked`` and ``channel_members``. ``last_24h`` is
counted by the application's clock, as in v1. ``failed_emails`` keeps v1's name but counts the
failed invitations (``lesson_invitation``) only: the retry, ``POST /admin/emails/retry``, sends
those, so the number falls to zero after it; v2 never sends v1's confirmation (requirements,
section 8). A failed email (section 6) is ``failed``, or ``pending`` longer than 15 minutes
since ``updated_at`` by the database clock, unless its ``scheduled_at`` is still ahead. Without
the admin token — the same 401 every time; a database failure — 503
``{"status": "unavailable"}``. Answers are never cached or indexed.
"""

from collections.abc import Callable
from datetime import timedelta

import pytest

from app.adapters.db.models import EMAIL_KINDS
from app.adapters.extras.keys import REPORTS
from app.core.entities import TelegramAccount
from app.services import override
from tests.conftest import REQUIRED_ENV, ParticipantFactory
from tests.extras.conftest import SiteFactory
from tests.extras.helpers import (
    STATS_KEYS,
    RecordingStore,
    Site,
    add_email,
    failing,
    unavailable,
)
from tests.fakes import WEBINAR_START

TOKEN = REQUIRED_ENV["ADMIN_TOKEN"]
ZERO = dict.fromkeys(STATS_KEYS, 0)


def stats(site: Site) -> dict[str, int]:
    response = site.admin("/admin/stats")
    assert response.status_code == 200
    numbers: dict[str, int] = response.json()
    return numbers


def test_the_keys_of_v1_come_first_then_the_new_ones(site: Site) -> None:
    assert list(stats(site)) == STATS_KEYS


def test_an_empty_database(site: Site) -> None:
    assert stats(site) == ZERO


def test_total_counts_participants_of_v1_and_v2(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant_factory(origin=None)
    participant_factory(origin=None)
    participant_factory()

    assert stats(site)["total"] == 3


def test_last_24h_is_counted_by_the_application_clock(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    now = WEBINAR_START  # the fake clock
    participant_factory(registered_at=now - timedelta(hours=24))  # the edge counts, as in v1
    participant_factory(registered_at=now - timedelta(hours=24, seconds=1))
    participant_factory(registered_at=now - timedelta(minutes=5), origin=None)
    participant_factory(registered_at=now - timedelta(days=3))

    assert stats(site)["last_24h"] == 2

    site.clock.advance(timedelta(hours=24))
    assert stats(site)["last_24h"] == 0


def test_failed_emails_follow_the_rule_of_a_failed_email(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    engine = site.engine
    counted = [
        ("failed", timedelta(0), None),
        ("pending", timedelta(minutes=16), None),  # its process died
        ("failed", timedelta(0), timedelta(hours=-1)),  # due already
        ("pending", timedelta(hours=3), timedelta(hours=-1)),
    ]
    not_counted = [
        ("pending", timedelta(minutes=14), None),  # still sending
        ("sent", timedelta(days=1), None),
        ("failed", timedelta(0), timedelta(hours=1)),  # scheduled ahead
        ("pending", timedelta(minutes=16), timedelta(hours=1)),
    ]
    for status, changed_ago, scheduled_in in counted + not_counted:
        add_email(
            engine,
            participant_factory().id,
            "lesson_invitation",
            status,
            changed_ago=changed_ago,
            scheduled_in=scheduled_in,
        )

    assert stats(site)["failed_emails"] == len(counted)


OTHER_KINDS = [kind for kind in EMAIL_KINDS if kind != "lesson_invitation"]


def test_failed_emails_count_invitations_only(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    """A failed confirmation of v1 would stay in the number for good: the retry never sends it."""
    assert "confirmation" in OTHER_KINDS
    for kind in OTHER_KINDS:
        add_email(site.engine, participant_factory().id, kind, "failed")
        add_email(
            site.engine,
            participant_factory().id,
            kind,
            "pending",
            changed_ago=timedelta(hours=1),
        )

    assert stats(site)["failed_emails"] == 0


def test_beside_a_failed_confirmation_the_failed_invitation_counts(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant = participant_factory()
    add_email(site.engine, participant.id, "confirmation", "failed")
    add_email(site.engine, participant.id, "lesson_invitation", "failed")

    assert stats(site)["failed_emails"] == 1


def test_telegram_linked_and_channel_members(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant_factory(telegram=TelegramAccount(3001), channel_member=True)
    participant_factory(telegram=TelegramAccount(3002, "second"), channel_member=True)
    participant_factory(telegram=TelegramAccount(3003), channel_member=False)
    participant_factory(telegram=TelegramAccount(3004))  # not checked yet
    participant_factory(origin=None)

    numbers = stats(site)

    assert (numbers["telegram_linked"], numbers["channel_members"]) == (4, 2)


def test_all_the_numbers_at_once(site: Site, participant_factory: ParticipantFactory) -> None:
    linked = participant_factory(telegram=TelegramAccount(4001), channel_member=True)
    participant_factory(origin=None, registered_at=WEBINAR_START - timedelta(days=2))
    add_email(site.engine, linked.id, "lesson_invitation", "failed")

    assert stats(site) == {
        "total": 2,
        "last_24h": 1,
        "failed_emails": 1,
        "telegram_linked": 1,
        "channel_members": 1,
    }


def test_answers_are_never_cached_or_indexed(site: Site) -> None:
    response = site.admin("/admin/stats")

    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-robots-tag"] == "noindex"


# --- access -------------------------------------------------------------------------------

REFUSED = {
    "no header": {},
    "wrong token": {"Authorization": "Bearer wrong-token-0123456789abcdef0123"},
    "token with a tail": {"Authorization": f"Bearer {TOKEN}x"},
    "another scheme": {"Authorization": f"Basic {TOKEN}"},
}


@pytest.mark.parametrize("headers", REFUSED.values(), ids=REFUSED.keys())
def test_without_the_admin_token_the_answer_is_the_same_401(
    site_factory: SiteFactory, headers: dict[str, str]
) -> None:
    store = RecordingStore()
    site = site_factory(overrides=[override(REPORTS, store)])

    response = site.admin("/admin/stats", headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-robots-tag"] == "noindex"
    assert store.calls == []


def test_the_scheme_is_case_insensitive(site: Site) -> None:
    response = site.admin("/admin/stats", headers={"Authorization": f"bearer {TOKEN}"})

    assert response.status_code == 200


# --- database failure ---------------------------------------------------------------------


@pytest.mark.parametrize("store", [unavailable, failing], ids=["outage", "broken statement"])
def test_a_database_failure_is_503(
    site_factory: SiteFactory, store: Callable[[], RecordingStore]
) -> None:
    site = site_factory(overrides=[override(REPORTS, store())])

    response = site.admin("/admin/stats")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-robots-tag"] == "noindex"
