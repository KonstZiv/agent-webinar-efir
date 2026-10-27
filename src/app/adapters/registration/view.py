"""What the partials of the slice show: ``_form.html``, ``_success.html`` and its parts.

``FormSettings`` is a template global (``registration``): the partial ``_form.html`` renders
only where the slice is installed. ``RegistrationState`` is what ``POST /register`` puts in
``section#register``: the form with the typed values and problems, the success screen, or the
notice of the staging site.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class FormSettings:
    """Values of the settings the partials need; none of them is a secret."""

    turnstile_site_key: str
    recording_youtube_id: str
    # The values ``{lesson_…}`` of docs/copy.md, section 11, by their names; none without a lesson.
    lesson: Mapping[str, str] | None = None


@dataclass(frozen=True, slots=True)
class RegistrationState:
    """The answer of ``POST /register``; a fresh form has none.

    ``email`` is what the visitor typed on the form, the normalised address on the screen.
    """

    email: str = ""
    consent: bool = False
    problems: frozenset[str] = field(default_factory=frozenset)
    registered: bool = False
    bot_url: str | None = None
    not_allowed: bool = False

    @property
    def screen(self) -> bool:
        """The success screen or the notice takes the place of the form."""
        return self.registered or self.not_allowed
