"""What ``_counters.html`` needs from the slice: the template global ``counters``.

Where the slice is not installed, the global is absent and the partial renders nothing.
"""

from dataclasses import dataclass

from app.core.extras.counters import REFRESH_SECONDS

COUNTERS_PATH = "/counters"


@dataclass(frozen=True, slots=True)
class CountersPartial:
    """The address the partial asks for its numbers and how often, in seconds."""

    url: str = COUNTERS_PATH
    refresh_seconds: int = REFRESH_SECONDS
