"""Slices plug into the application here, by adding one module each (requirements, section 12).

A module ``app/slices/<slice>.py`` defines ``install(setup: SliceSetup) -> None``.
``create_app`` imports every module of this package in the order of their names and calls
``install`` before it builds the application; ``main.py`` and ``dependencies.py`` never name a
slice. In ``install`` a slice:

- provides its adapters and use cases by key, chosen by the settings (``setup.provide``);
  its own keys are named ``<slice>.<name>``; a test's override of a key wins, and the real
  adapter is not built;
- adds middleware (``setup.add_middleware``, ``setup.http_middleware``);
- adds start-up and shut-down actions and closers (``setup.on_startup``,
  ``setup.on_shutdown``, ``setup.close_on_shutdown``);
- gives templates values its partials need (``setup.template_global``).

Routes of a slice live in ``app/adapters/web/routers/<slice>.py`` (or ``<slice>_*.py``) and
get services with ``Depends(service(KEY))``. The redirect stub installs no slice.
"""

import dataclasses
import importlib
import inspect
import pkgutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from types import ModuleType
from typing import NamedTuple

from sqlalchemy import Engine
from starlette.middleware import Middleware, _MiddlewareFactory
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.services import SHARED_KEYS, Key, Services
from app.settings import Settings

# A start-up or shut-down action: a plain or an async function without arguments.
type Action = Callable[[], object]
type Dispatch = Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]
type Install = Callable[[SliceSetup], None]


class Slice(NamedTuple):
    """A slice found in ``app.slices``: the module name and its ``install``."""

    name: str
    install: Install


@dataclass
class SliceSetup:
    """What ``create_app`` gives each slice's ``install``; it collects what the slice adds.

    ``slice`` names the slice being installed (``for_slice``); what the slices add goes to the
    same lists.
    """

    settings: Settings
    services: Services
    _engine: Callable[[], Engine] = field(repr=False)
    slice: str = ""
    middleware: list[Middleware] = field(default_factory=list)
    startup: list[Action] = field(default_factory=list)
    shutdown: list[Action] = field(default_factory=list)
    closers: list[Callable[[], None]] = field(default_factory=list)
    template_globals: dict[str, object] = field(default_factory=dict)

    def engine(self) -> Engine:
        """The application's database engine, created on first call and disposed on exit."""
        return self._engine()

    def for_slice(self, name: str) -> SliceSetup:
        """The setup that the slice ``name`` installs with; the collected lists are shared."""
        return dataclasses.replace(self, slice=name)

    def provide[T](self, key: Key[T], build: Callable[[], T]) -> None:
        """Provide the service ``key``: ``build`` runs on first use, unless a test overrides it.

        The slice's own key is named ``<slice>.<name>``; a shared port keeps its key
        (``app.services.SHARED_KEYS``).
        """
        if key.name not in SHARED_KEYS and not key.name.startswith(f"{self.slice}."):
            raise ValueError(
                f"slice {self.slice!r}: name its own key {key.name!r} «{self.slice}.<name>»"
            )
        self.services.provide(key, build)

    def add_middleware[**P](
        self, middleware_class: _MiddlewareFactory[P], *args: P.args, **kwargs: P.kwargs
    ) -> None:
        """An ASGI middleware, as ``FastAPI.add_middleware`` takes it."""
        self.middleware.append(Middleware(middleware_class, *args, **kwargs))

    def http_middleware(self, dispatch: Dispatch) -> None:
        """A function middleware, as ``@app.middleware("http")`` takes it."""
        self.add_middleware(BaseHTTPMiddleware, dispatch=dispatch)

    def on_startup(self, action: Action) -> None:
        """Run ``action`` when the application starts, after the slices registered earlier.

        Not critical by design: an exception is logged by class and the application starts.
        """
        self.startup.append(action)

    def on_shutdown(self, action: Action) -> None:
        """Run ``action`` when the application stops; the last registered runs first.

        An exception is logged by class; the other actions and the closers still run.
        """
        self.shutdown.append(action)

    def close_on_shutdown(self, close: Callable[[], None]) -> None:
        """Release a resource (a client, a pool) after the shut-down actions."""
        self.closers.append(close)

    def template_global(self, name: str, value: object) -> None:
        """A value every template sees, for the slice's partials."""
        if name in self.template_globals:
            raise ValueError(f"template global {name} is set twice")
        self.template_globals[name] = value


async def run_action(action: Action) -> None:
    """Call ``action``; await its result when it is a coroutine."""
    result = action()
    if inspect.isawaitable(result):
        await result


def discover_slices(package: ModuleType) -> list[Slice]:
    """Import every module of ``package``; return its name and ``install``, by module name.

    A module without a callable ``install`` is a mistake, not something to skip.
    """
    found: list[Slice] = []
    for module_info in sorted(pkgutil.iter_modules(package.__path__), key=lambda m: m.name):
        module = importlib.import_module(f"{package.__name__}.{module_info.name}")
        install = getattr(module, "install", None)
        if not callable(install):
            raise TypeError(f"Slice module {module.__name__} must define `install(setup)`")
        found.append(Slice(module_info.name, install))
    return found
