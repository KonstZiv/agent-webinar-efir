"""The geometry of the inline SVG chart of ``/stats``: one bar per hour, no scripts or libraries.

The chart scales with the page (``viewBox``, no fixed size); bars are as high as their share of
the busiest hour, so the tallest fills the plot.
"""

from dataclasses import dataclass

from app.core.stats.view import Hour

WIDTH = 480
PLOT_HEIGHT = 120
HEIGHT = 144  # the plot and a line of labels under it
PITCH = 10
GAP = 2
LABEL_Y = 138


@dataclass(frozen=True, slots=True)
class Bar:
    x: int
    y: int
    width: int
    height: int
    count: int
    label: str


@dataclass(frozen=True, slots=True)
class Chart:
    bars: tuple[Bar, ...]
    width: int
    height: int
    plot_height: int
    label_y: int
    first_label: str
    last_label: str


def build_chart(hours: tuple[Hour, ...]) -> Chart:
    """A bar for each hour; a registered hour is at least 2 units high, so it never vanishes."""
    peak = max((hour.count for hour in hours), default=0)
    bars = []
    for number, hour in enumerate(hours):
        height = max(2, round(hour.count / peak * PLOT_HEIGHT)) if hour.count else 0
        bars.append(
            Bar(
                x=number * PITCH + GAP // 2,
                y=PLOT_HEIGHT - height,
                width=PITCH - GAP,
                height=height,
                count=hour.count,
                label=hour.label,
            )
        )
    return Chart(
        bars=tuple(bars),
        width=WIDTH,
        height=HEIGHT,
        plot_height=PLOT_HEIGHT,
        label_y=LABEL_Y,
        first_label=hours[0].label if hours else "",
        last_label=hours[-1].label if hours else "",
    )
