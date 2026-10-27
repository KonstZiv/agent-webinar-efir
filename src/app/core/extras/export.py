"""Cells of the export ``GET /admin/export.csv`` (docs/requirements.md, section 8).

Columns in the order of the requirements; ``registered_at`` in UTC to the second; flags as
``0``/``1``, a check never made as an empty cell, an empty value as an empty cell. Visitors set
``utm_*`` and the local part of an address, and the file is opened in a spreadsheet, so a cell
that a spreadsheet would read as a formula gets ``'`` in front.
"""

from datetime import UTC, datetime

from app.core.extras.ports import ExportRow

COLUMNS = (
    "email",
    "registered_at",
    "origin",
    "telegram_linked",
    "channel_member",
    "level",
    "ref_code",
    "referrals",
    "groups",
    "attended",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
)
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def protect(value: str) -> str:
    """Defuse a value a spreadsheet would run as a formula.

    >>> protect("=HYPERLINK(1)"), protect("-3"), protect("telegram"), protect("")
    ("'=HYPERLINK(1)", "'-3", 'telegram', '')
    """
    return f"'{value}" if value.startswith(FORMULA_STARTS) else value


def utc_moment(moment: datetime) -> str:
    """``2026-10-20T16:05:00Z``: UTC, to the second.

    >>> from datetime import timedelta, timezone
    >>> utc_moment(datetime(2026, 10, 20, 19, 5, 0, 999, tzinfo=timezone(timedelta(hours=3))))
    '2026-10-20T16:05:00Z'
    """
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _flag(value: bool | None) -> str:
    return "" if value is None else str(int(value))


def cells(row: ExportRow) -> tuple[str, ...]:
    """The row's cells in the order of ``COLUMNS``, each one protected."""
    values = (
        row.email,
        utc_moment(row.registered_at),
        row.origin,
        _flag(row.telegram_linked),
        _flag(row.channel_member),
        row.level,
        row.ref_code,
        str(row.referrals),
        ";".join(row.groups),
        ";".join(day.isoformat() for day in row.attended),
        row.utm_source,
        row.utm_medium,
        row.utm_campaign,
        row.utm_content,
    )
    return tuple(protect(value or "") for value in values)
