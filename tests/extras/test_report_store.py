"""``SqlReportStore`` on the shared tables: one statement per report, so the numbers agree.

The routes' tests check the reports through HTTP; these check the queries themselves and that a
database failure becomes an exception of the port.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine

from app.adapters.db.engine import make_engine
from app.adapters.extras.reports import SqlReportStore
from app.core.entities import TelegramAccount
from app.core.extras.ports import Counts, ExportRow, Stats
from app.core.extras.statistics import STALE_PENDING_AFTER
from app.core.ports import StorageUnavailable
from tests.conftest import ParticipantFactory
from tests.extras.helpers import add_email, set_columns

SINCE = datetime(2026, 10, 19, 16, 0, tzinfo=UTC)


def test_counts(migrated_engine: Engine, participant_factory: ParticipantFactory) -> None:
    participant_factory(origin=None)
    participant_factory(telegram=TelegramAccount(7001), channel_member=False)
    participant_factory(telegram=TelegramAccount(7002), channel_member=True)

    assert SqlReportStore(migrated_engine).counts() == Counts(registered=3, telegram_linked=2)


def test_stats(migrated_engine: Engine, participant_factory: ParticipantFactory) -> None:
    recent = participant_factory(registered_at=SINCE + timedelta(hours=1))
    linked = participant_factory(
        origin=None, registered_at=SINCE - timedelta(days=1), telegram=TelegramAccount(7101)
    )
    member = participant_factory(telegram=TelegramAccount(7102), channel_member=True)
    stale = timedelta(hours=1)
    add_email(migrated_engine, recent.id, "lesson_invitation", "failed")
    add_email(migrated_engine, recent.id, "confirmation", "failed")  # not an invitation
    add_email(migrated_engine, linked.id, "lesson_invitation", "pending", changed_ago=stale)
    add_email(migrated_engine, linked.id, "confirmation", "pending", changed_ago=stale)
    add_email(migrated_engine, member.id, "lesson_invitation", "sent")

    found = SqlReportStore(migrated_engine).stats(SINCE, STALE_PENDING_AFTER)

    assert found == Stats(
        total=3, last_24h=2, failed_emails=2, telegram_linked=2, channel_members=1
    )


def test_export_rows(migrated_engine: Engine, participant_factory: ParticipantFactory) -> None:
    later = participant_factory("later@example.com", registered_at=SINCE + timedelta(hours=2))
    participant_factory(
        "earlier@example.com",
        origin=None,
        registered_at=SINCE,
        telegram=TelegramAccount(7201, "early_bird"),
        channel_member=True,
        level="senior",
    )
    set_columns(migrated_engine, later.id, utm_source="ads", utm_content="banner")

    rows = SqlReportStore(migrated_engine).export_rows()

    assert [(row.email, row.registered_at) for row in rows] == [
        ("earlier@example.com", SINCE),
        ("later@example.com", SINCE + timedelta(hours=2)),
    ]
    assert rows[0] == ExportRow(
        email="earlier@example.com",
        registered_at=rows[0].registered_at,
        origin=None,
        telegram_linked=True,
        channel_member=True,
        level="senior",
        utm_source=None,
        utm_medium=None,
        utm_campaign=None,
        utm_content=None,
        telegram_user_id=7201,
        telegram_username="early_bird",
    )
    assert (rows[1].telegram_user_id, rows[1].telegram_username) == (None, None)
    assert (rows[1].origin, rows[1].telegram_linked, rows[1].channel_member) == ("v2", False, None)
    assert (rows[1].utm_source, rows[1].utm_content) == ("ads", "banner")


def test_rows_registered_at_the_same_moment_keep_the_order_of_insertion(
    migrated_engine: Engine, participant_factory: ParticipantFactory
) -> None:
    for name in ("one", "two", "three"):
        participant_factory(f"{name}@example.com", registered_at=SINCE)

    emails = [row.email for row in SqlReportStore(migrated_engine).export_rows()]

    assert emails == ["one@example.com", "two@example.com", "three@example.com"]


@pytest.mark.parametrize("report", ["counts", "stats", "export_rows"])
def test_an_unreachable_database_is_storage_unavailable(report: str) -> None:
    engine = make_engine("postgresql+psycopg://app@127.0.0.1:1/none")
    store = SqlReportStore(engine)
    calls = {
        "counts": store.counts,
        "stats": lambda: store.stats(SINCE, STALE_PENDING_AFTER),
        "export_rows": store.export_rows,
    }

    try:
        with pytest.raises(StorageUnavailable):
            calls[report]()
    finally:
        engine.dispose()
