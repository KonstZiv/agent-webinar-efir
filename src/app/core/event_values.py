"""The webinar's date and time as texts show them: values ``{event_…}`` of docs/copy.md.

Texts never carry the date of the webinar (docs/requirements.md, section 16): docs/copy.md marks
it with values (section 11), and the site fills them from ``EVENT_START`` and ``EVENT_END`` —
naive Kyiv wall time. Moving the webinar is a change of these two settings.

>>> values = event_values(datetime(2026, 10, 21, 19, 0), datetime(2026, 10, 21, 21, 0))
>>> values.weekday_capital, values.date, values.start, values.end
('Середа', '21 жовтня 2026 року', '19:00', '21:00')
>>> values.placeholders()["event_day_month"]
'21 жовтня'
"""

from dataclasses import asdict, dataclass
from datetime import datetime

from app.core.timezone import in_kyiv

WEEKDAYS = ("понеділок", "вівторок", "середа", "четвер", "п'ятниця", "субота", "неділя")
# Months in the genitive: «21 жовтня».
MONTHS = (
    "січня",
    "лютого",
    "березня",
    "квітня",
    "травня",
    "червня",
    "липня",
    "серпня",
    "вересня",
    "жовтня",
    "листопада",
    "грудня",
)
PREFIX = "event_"


@dataclass(frozen=True, slots=True)
class EventValues:
    """Each field is the value ``{event_<field>}`` of docs/copy.md, section 11."""

    weekday: str  # «середа»
    weekday_capital: str  # «Середа»
    date: str  # «21 жовтня 2026 року»
    day_month: str  # «21 жовтня»
    start: str  # «19:00»
    end: str  # «21:00»
    start_moment: str  # «2026-10-21T19:00+03:00»: Kyiv time with the zone's offset on that day
    end_moment: str

    def placeholders(self) -> dict[str, str]:
        """Names as copy.md writes them, without braces, mapped to the values.

        >>> values = event_values(datetime(2026, 10, 21, 19), datetime(2026, 10, 21, 21))
        >>> sorted(values.placeholders())[:2]
        ['event_date', 'event_day_month']
        """
        return {f"{PREFIX}{name}": value for name, value in asdict(self).items()}


def _moment(local: datetime) -> str:
    return in_kyiv(local).isoformat(timespec="minutes")


def event_values(start: datetime, end: datetime) -> EventValues:
    """Values of the webinar that starts and ends at naive Kyiv wall times ``start``, ``end``.

    >>> event_values(datetime(2026, 11, 3, 18, 30), datetime(2026, 11, 3, 20, 15)).start_moment
    '2026-11-03T18:30+02:00'
    """
    weekday = WEEKDAYS[start.weekday()]
    day_month = f"{start.day} {MONTHS[start.month - 1]}"
    return EventValues(
        weekday=weekday,
        weekday_capital=weekday[0].upper() + weekday[1:],
        date=f"{day_month} {start.year} року",
        day_month=day_month,
        start=f"{start:%H:%M}",
        end=f"{end:%H:%M}",
        start_moment=_moment(start),
        end_moment=_moment(end),
    )
