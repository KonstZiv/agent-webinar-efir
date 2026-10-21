"""``GET /admin/export.csv`` (docs/requirements.md, section 8; docs/contract.md, section 8).

UTF-8 without BOM, commas, a header row, ``Content-Disposition: attachment;
filename=participants.csv``. Columns in this order: ``email``, ``registered_at`` (UTC,
``2026-10-20T16:05:00Z``), ``origin``, ``telegram_linked`` (``0``/``1``), ``channel_member``
(``0``/``1``/empty), ``level``, ``utm_source``, ``utm_medium``, ``utm_campaign``,
``utm_content``. Rows by ``registered_at``, the earliest first; an empty value is an empty cell.
A value starting with ``=``, ``+``, ``-``, ``@``, a tab or a carriage return gets ``'`` in front.
No unsubscribe links, no ad click or Google Analytics identifiers. The file is parsed in memory
only: never printed, never stored.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.adapters.extras.keys import REPORTS
from app.core.entities import TelegramAccount
from app.core.extras.export import cells, protect
from app.core.extras.ports import ExportRow
from app.services import override
from tests.conftest import ParticipantFactory
from tests.extras.conftest import SiteFactory
from tests.extras.helpers import (
    EXPORT_COLUMNS,
    RecordingStore,
    Site,
    csv_rows,
    failing,
    set_columns,
    unavailable,
)

KYIV_SUMMER = timezone(timedelta(hours=3))


def export(site: Site) -> list[list[str]]:
    response = site.admin("/admin/export.csv")
    assert response.status_code == 200
    return csv_rows(response)


def by_email(rows: list[list[str]]) -> dict[str, dict[str, str]]:
    header, *body = rows
    return {row[0]: dict(zip(header, row, strict=True)) for row in body}


# --- the file -----------------------------------------------------------------------------


def test_an_empty_database_gives_the_header_only(site: Site) -> None:
    assert export(site) == [EXPORT_COLUMNS]


def test_the_file_is_an_attachment_in_utf8_without_bom(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant = participant_factory()
    set_columns(site.engine, participant.id, utm_campaign="осінь-2026")

    response = site.admin("/admin/export.csv")

    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == "attachment; filename=participants.csv"
    assert not response.content.startswith(b"\xef\xbb\xbf")
    assert "осінь-2026".encode() in response.content


def test_lines_end_as_rfc_4180_says(site: Site, participant_factory: ParticipantFactory) -> None:
    participant_factory()

    text = site.admin("/admin/export.csv").content.decode()

    assert text.startswith(",".join(EXPORT_COLUMNS) + "\r\n")
    assert text.endswith("\r\n")
    assert text.count("\r\n") == 2


def test_answers_are_never_cached_or_indexed(site: Site) -> None:
    response = site.admin("/admin/export.csv")

    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-robots-tag"] == "noindex"


# --- rows and values ----------------------------------------------------------------------


def test_rows_go_from_the_earliest_registration(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    start = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    for name, day in (("third", 3), ("first", 1), ("second", 2)):
        participant_factory(f"{name}@example.com", registered_at=start + timedelta(days=day))

    emails = [row[0] for row in export(site)[1:]]

    assert emails == ["first@example.com", "second@example.com", "third@example.com"]


def test_registered_at_is_utc_to_the_second(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    moment = datetime(2026, 10, 20, 19, 5, 0, 123456, tzinfo=KYIV_SUMMER)
    participant_factory("kyiv@example.com", registered_at=moment)

    assert by_email(export(site))["kyiv@example.com"]["registered_at"] == "2026-10-20T16:05:00Z"


def test_every_column_of_a_full_row(site: Site, participant_factory: ParticipantFactory) -> None:
    participant = participant_factory(
        "full@example.com",
        registered_at=datetime(2026, 10, 20, 16, 5, tzinfo=UTC),
        telegram=TelegramAccount(5001, "full"),
        channel_member=True,
        level="middle",
    )
    set_columns(
        site.engine,
        participant.id,
        utm_source="telegram",
        utm_medium="social",
        utm_campaign="webinar",
        utm_content="post-1",
    )

    assert export(site)[1] == [
        "full@example.com",
        "2026-10-20T16:05:00Z",
        "v2",
        "1",
        "1",
        "middle",
        "telegram",
        "social",
        "webinar",
        "post-1",
    ]


def test_a_participant_of_v1_has_empty_cells(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant_factory("old@example.com", origin=None)

    row = by_email(export(site))["old@example.com"]

    assert row["origin"] == ""
    assert row["telegram_linked"] == "0"
    assert [row[name] for name in EXPORT_COLUMNS[4:]] == [""] * 6


@pytest.mark.parametrize(
    ("telegram", "member", "cells_shown"),
    [
        (None, None, ("0", "")),
        (TelegramAccount(6001), None, ("1", "")),
        (TelegramAccount(6002), False, ("1", "0")),
        (TelegramAccount(6003), True, ("1", "1")),
    ],
    ids=["not linked", "never checked", "not a member", "member"],
)
def test_telegram_and_channel_cells(
    site: Site,
    participant_factory: ParticipantFactory,
    telegram: TelegramAccount | None,
    member: bool | None,
    cells_shown: tuple[str, str],
) -> None:
    participant_factory("tg@example.com", telegram=telegram, channel_member=member)

    row = by_email(export(site))["tg@example.com"]

    assert (row["telegram_linked"], row["channel_member"]) == cells_shown


def test_commas_and_quotes_survive(site: Site, participant_factory: ParticipantFactory) -> None:
    participant = participant_factory("quotes@example.com")
    set_columns(site.engine, participant.id, utm_campaign='spring, "sale"\nline two')

    row = by_email(export(site))["quotes@example.com"]

    assert row["utm_campaign"] == 'spring, "sale"\nline two'


# --- formulas -----------------------------------------------------------------------------

DANGEROUS = ["=HYPERLINK(1)", "+1+2", "-3", "@SUM(A1)", "\tTAB", "\rCR"]


@pytest.mark.parametrize("value", DANGEROUS, ids=["equals", "plus", "minus", "at", "tab", "cr"])
def test_a_formula_from_the_address_bar_is_defused(
    site: Site, participant_factory: ParticipantFactory, value: str
) -> None:
    participant = participant_factory("formula@example.com")
    set_columns(
        site.engine,
        participant.id,
        utm_source=value,
        utm_medium=value,
        utm_campaign=value,
        utm_content=value,
    )

    row = by_email(export(site))["formula@example.com"]

    assert [row[name] for name in EXPORT_COLUMNS[-4:]] == [f"'{value}"] * 4


def test_a_formula_in_the_local_part_of_an_address_is_defused(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant_factory("=1+2@example.com", level="-junior")

    rows = export(site)

    assert rows[1][0] == "'=1+2@example.com"
    assert rows[1][EXPORT_COLUMNS.index("level")] == "'-junior"


def test_values_with_signs_inside_are_left_alone(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant = participant_factory("a-b@example.com")
    set_columns(site.engine, participant.id, utm_source="a=b", utm_medium="x+y")

    row = by_email(export(site))["a-b@example.com"]

    assert (row["utm_source"], row["utm_medium"]) == ("a=b", "x+y")


def test_protect() -> None:
    assert [protect(value) for value in DANGEROUS] == [f"'{value}" for value in DANGEROUS]
    assert protect("") == ""
    assert protect("telegram") == "telegram"
    assert protect("'=quoted") == "'=quoted"


def test_cells_of_a_row() -> None:
    row = ExportRow(
        email="cells@example.com",
        registered_at=datetime(2026, 10, 20, 19, 5, 30, tzinfo=KYIV_SUMMER),
        origin=None,
        telegram_linked=True,
        channel_member=False,
        level=None,
        utm_source="@me",
        utm_medium=None,
        utm_campaign=None,
        utm_content="",
    )

    assert cells(row) == (
        "cells@example.com",
        "2026-10-20T16:05:30Z",
        "",
        "1",
        "0",
        "",
        "'@me",
        "",
        "",
        "",
    )


# --- what the file never holds ------------------------------------------------------------


def test_no_unsubscribe_links_and_no_click_or_analytics_identifiers(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant = participant_factory("private@example.com")
    hidden = {
        "gclid": "SENTINEL-GCLID",
        "gbraid": "SENTINEL-GBRAID",
        "wbraid": "SENTINEL-WBRAID",
        "ga_client_id": "1234567890.987654321",
        "utm_term": "SENTINEL-TERM",
        "landing_url": "https://example.com/?SENTINEL-LANDING",
        "referrer": "https://example.com/SENTINEL-REFERRER",
    }
    set_columns(site.engine, participant.id, **hidden)

    response = site.admin("/admin/export.csv")
    text = response.content.decode()

    assert csv_rows(response)[0] == EXPORT_COLUMNS
    assert [name for name, value in hidden.items() if value in text] == []
    assert str(participant.unsubscribe_id) not in text
    assert "unsubscribe" not in text


# --- access and failures ------------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong-token-0123456789abcdef0123"}],
    ids=["no header", "wrong token"],
)
def test_without_the_admin_token_there_is_no_file(
    site_factory: SiteFactory, headers: dict[str, str]
) -> None:
    store = RecordingStore()
    site = site_factory(overrides=[override(REPORTS, store)])

    response = site.admin("/admin/export.csv", headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
    assert response.headers["www-authenticate"] == "Bearer"
    assert "content-disposition" not in response.headers
    assert store.calls == []


@pytest.mark.parametrize("store", [unavailable, failing], ids=["outage", "broken statement"])
def test_a_database_failure_is_503(
    site_factory: SiteFactory, store: Callable[[], RecordingStore]
) -> None:
    site = site_factory(overrides=[override(REPORTS, store())])

    response = site.admin("/admin/export.csv")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert response.headers["cache-control"] == "no-store"
    assert "content-disposition" not in response.headers


def test_the_log_holds_no_participant_data(
    site: Site, participant_factory: ParticipantFactory, caplog: pytest.LogCaptureFixture
) -> None:
    participant_factory("logged@example.com")

    with caplog.at_level("INFO"):
        site.admin("/admin/export.csv")

    app_log = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("app."))
    assert "logged" not in app_log
    assert "example.com" not in app_log
