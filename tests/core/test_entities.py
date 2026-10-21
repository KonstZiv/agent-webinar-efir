"""``TrafficSource`` holds only what the shared table can store (docs/requirements.md, section 10).

Its values come from the visitor's address bar: NUL and lone surrogates are dropped, the rest is
cut to the column length; an empty value is ``None``, as v1 stores it.
"""

from dataclasses import fields

import pytest

from app.adapters.db.models import Participant as ParticipantRow
from app.core.entities import SOURCE_VALUE_LENGTH, TrafficSource

FIELDS = [item.name for item in fields(TrafficSource)]


@pytest.mark.parametrize("name", FIELDS)
def test_unstorable_characters_are_dropped(name: str) -> None:
    source = TrafficSource(**{name: "tele\x00gr\ud800am"})

    assert getattr(source, name) == "telegram"


@pytest.mark.parametrize("name", FIELDS)
def test_values_are_cut_to_the_column_length(name: str) -> None:
    source = TrafficSource(**{name: "\x00" + "a" * (SOURCE_VALUE_LENGTH + 100)})

    assert getattr(source, name) == "a" * SOURCE_VALUE_LENGTH


@pytest.mark.parametrize("raw", ["", "\x00", "\ud800\x00"])
def test_nothing_left_is_no_value(raw: str) -> None:
    assert TrafficSource(utm_source=raw).utm_source is None


def test_clean_values_stay_as_they_are() -> None:
    source = TrafficSource(utm_source="telegram", landing_url="https://agent.example.com/?a=1")

    assert source == TrafficSource(
        utm_source="telegram", landing_url="https://agent.example.com/?a=1"
    )
    assert source.utm_medium is None


@pytest.mark.parametrize("name", FIELDS)
def test_the_length_is_the_length_of_the_column(name: str) -> None:
    assert ParticipantRow.__table__.c[name].type.length == SOURCE_VALUE_LENGTH
