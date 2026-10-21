"""Services of the application by typed key: adapters and use cases the slices provide.

A slice provides a builder under a key; routes and other slices get the service by the same
key, never by importing the slice. A builder runs once, on first use, so creating the
application builds no client and reaches no network. A test overrides a key with a fake: the
real adapter is then never built.

>>> GREETING = Key[str]("greeting")
>>> services = Services([override(GREETING, "fake")])
>>> services.provide(GREETING, lambda: "real")
>>> services.get(GREETING)
'fake'

The keys below name the shared ports (``app.core.ports``). The foundation provides the clock
and the stores; the slice «реєстрація і лист» provides the email sender and the human check;
the slice «бот» provides the messenger. A slice names its own keys after itself,
``<slice>.<name>`` (``SliceSetup.provide`` checks it): slices written in parallel never pick
the same name.
"""

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import cast

from app.core.ports import (
    Clock,
    EmailSender,
    HumanCheck,
    LinkTokenStore,
    Messenger,
    ParticipantStore,
)


@dataclass(frozen=True, slots=True)
class Key[T]:
    """Name of a service of type ``T``; names are unique across the application."""

    name: str


@dataclass(frozen=True, slots=True)
class Override:
    """A value that replaces a service; made by ``override``, which checks its type."""

    name: str
    value: object


def override[T](key: Key[T], value: T) -> Override:
    """Replace the service ``key`` with ``value`` (in tests: a fake)."""
    return Override(key.name, value)


class Services:
    """Builders of services by key, overrides first; thread-safe on first use."""

    def __init__(self, overrides: Iterable[Override] = ()) -> None:
        self._built: dict[str, object] = {}
        for item in overrides:
            if item.name in self._built:
                raise ValueError(f"service {item.name} is overridden twice")
            self._built[item.name] = item.value
        self._builders: dict[str, Callable[[], object]] = {}
        self._lock = threading.RLock()  # a builder may get another service

    def provide[T](self, key: Key[T], build: Callable[[], T]) -> None:
        """Register how to build ``key``; an override of the key wins over it."""
        if key.name in self._builders:
            raise ValueError(f"service {key.name} is provided twice")
        self._builders[key.name] = build

    def get[T](self, key: Key[T]) -> T:
        """The service ``key``, built on first use; ``LookupError`` if nobody provides it."""
        found = self.find(key)
        if found is None:
            raise LookupError(f"no service {key.name}: no slice provides it")
        return found

    def find[T](self, key: Key[T]) -> T | None:
        """The service ``key``, or ``None`` if nobody provides it."""
        with self._lock:
            if key.name not in self._built:
                build = self._builders.get(key.name)
                if build is None:
                    return None
                self._built[key.name] = build()
            return cast(T, self._built[key.name])


CLOCK = Key[Clock]("clock")
PARTICIPANTS = Key[ParticipantStore]("participants")
LINK_TOKENS = Key[LinkTokenStore]("link_tokens")
EMAIL_SENDER = Key[EmailSender]("email_sender")
HUMAN_CHECK = Key[HumanCheck]("human_check")
MESSENGER = Key[Messenger]("messenger")

# Names a slice may provide without its own prefix.
SHARED_KEYS = frozenset(
    key.name for key in (CLOCK, PARTICIPANTS, LINK_TOKENS, EMAIL_SENDER, HUMAN_CHECK, MESSENGER)
)
