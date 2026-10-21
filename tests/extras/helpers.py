"""Helpers of the slice tests: the application on the test database, rows, stand-in stores.

``Site`` is the application of ``create_app`` on the migrated test database: the participant
rows are real, the clock and the outside services are fakes (tests/fakes.py). Addresses are
``…@example.com`` only. The export is parsed in memory and never printed or stored.
"""

import csv
import io
import threading
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, insert, update

from app.adapters.db.models import EmailRecord, Participant
from app.core.extras.ports import Counts, ExportRow, Stats
from app.core.ports import StorageError, StorageUnavailable
from tests.conftest import REQUIRED_ENV
from tests.fakes import FixedClock

ADMIN = {"Authorization": f"Bearer {REQUIRED_ENV['ADMIN_TOKEN']}"}
# Columns of the export in the order of docs/requirements.md, section 8 (the test's own copy).
EXPORT_COLUMNS = [
    "email",
    "registered_at",
    "origin",
    "telegram_linked",
    "channel_member",
    "level",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
]
STATS_KEYS = ["total", "last_24h", "failed_emails", "telegram_linked", "channel_members"]
HOLD_LIMIT = 10.0  # seconds a held read waits at most, so a broken test cannot hang


@dataclass
class Site:
    client: TestClient
    engine: Engine
    clock: FixedClock

    def admin(self, path: str, headers: dict[str, str] | None = None) -> httpx.Response:
        """``GET path`` with the admin token unless ``headers`` replace it."""
        return self.client.get(path, headers=ADMIN if headers is None else headers)


def set_columns(engine: Engine, participant_id: int, **values: object) -> None:
    """Write columns the participant factory does not take (``utm_*``, ``gclid``, …)."""
    with engine.begin() as connection:
        connection.execute(
            update(Participant).where(Participant.id == participant_id).values(**values)
        )


def add_email(
    engine: Engine,
    participant_id: int,
    kind: str,
    status: str,
    *,
    changed_ago: timedelta = timedelta(0),
    scheduled_in: timedelta | None = None,
) -> None:
    """An ``emails`` row changed ``changed_ago`` before now and scheduled ``scheduled_in`` from
    now (negative: in the past), both by the database clock, as the «failed email» rule reads
    them."""
    with engine.begin() as connection:
        connection.execute(
            insert(EmailRecord).values(
                participant_id=participant_id,
                kind=kind,
                status=status,
                idempotency_key=uuid.uuid4(),
                attempts=0,
                updated_at=func.now() - changed_ago,
                scheduled_at=None if scheduled_in is None else func.now() + scheduled_in,
            )
        )


def csv_rows(response: httpx.Response) -> list[list[str]]:
    """The export as rows of cells, the header first."""
    return list(csv.reader(io.StringIO(response.content.decode("utf-8"), newline="")))


@dataclass
class RecordingStore:
    """A ``ReportStore`` with fixed answers that counts its calls, or fails with ``error``."""

    counted: Counts = field(default_factory=lambda: Counts(registered=0, telegram_linked=0))
    error: StorageError | None = None
    calls: list[str] = field(default_factory=list)

    def counts(self) -> Counts:
        self.calls.append("counts")
        if self.error is not None:
            raise self.error
        return self.counted

    def stats(self, registered_since: Any, stale_after: Any) -> Stats:
        self.calls.append("stats")
        if self.error is not None:
            raise self.error
        return Stats(total=0, last_24h=0, failed_emails=0, telegram_linked=0, channel_members=0)

    def export_rows(self) -> list[ExportRow]:
        self.calls.append("export_rows")
        if self.error is not None:
            raise self.error
        return []


@dataclass
class SlowStore(RecordingStore):
    """A ``RecordingStore`` whose ``counts``, while ``held``, waits until ``done`` is set: a slow
    database. ``reading`` is set once such a read has begun."""

    held: bool = False
    reading: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)

    def counts(self) -> Counts:
        if self.held:
            self.reading.set()
            self.done.wait(HOLD_LIMIT)
        return super().counts()


def unavailable() -> RecordingStore:
    """The database is down: every call raises ``StorageUnavailable``."""
    return RecordingStore(error=StorageUnavailable("test"))


def failing() -> RecordingStore:
    """Every call raises a bare ``StorageError``: a broken statement, not an outage."""
    return RecordingStore(error=StorageError("test"))
