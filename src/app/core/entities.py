"""Entities the ports exchange with the core."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HumanCheckResult:
    """Verdict of the check that a person fills in a form (Turnstile)."""

    success: bool
    hostname: str | None = None
