"""Composition root: ``create_app`` builds the application from settings and adapters.

Run with ``uvicorn app.main:create_app --factory``; there is no module-level app, so
importing this module needs no environment variables.
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine

from app import slices
from app.adapters.clock import SystemClock
from app.adapters.content.copy import load_page_texts
from app.adapters.content.legal import load_legal_texts
from app.adapters.db.engine import make_engine
from app.adapters.db.link_tokens import SqlLinkTokenStore
from app.adapters.db.participants import SqlParticipantStore
from app.adapters.db.probe import SqlDatabaseProbe
from app.adapters.web import routers
from app.adapters.web.access_log import install_access_log_filter
from app.adapters.web.dependencies import STATIC_DIR, Container, make_templates
from app.adapters.web.headers import NOINDEX
from app.adapters.web.page_meta import build_page_meta
from app.adapters.web.redirect import RedirectEverything
from app.adapters.web.routing import discover_routers
from app.adapters.web.token_paths import NoReferrerOnTokenPaths
from app.core.event_values import EventValues, event_values
from app.core.ports import DatabaseProbe
from app.services import CLOCK, LINK_TOKENS, PARTICIPANTS, Override, Services
from app.settings import Settings, load_settings
from app.slices import Action, SliceSetup, discover_slices, run_action

# Texts live in the repository's docs/; on Railway the working directory is the repository
# root (/app).
DOCS_DIR = Path("docs")

type Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """INFO records of the ``app`` loggers reach stderr (Railway logs); idempotent.

    Records still propagate to the root logger, so pytest's ``caplog`` sees them. The uvicorn
    access log gets tokens in paths masked.
    """
    logger = logging.getLogger("app")
    if logger.level == logging.NOTSET:
        logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
    install_access_log_filter()


def lifespan(
    startup: Sequence[Action] = (),
    shutdown: Sequence[Action] = (),
    *closers: Sequence[Callable[[], None]],
) -> Lifespan:
    """Run ``startup`` in order; on exit run ``shutdown`` in reverse, then every closer in order.

    No action is critical: its exception is logged by class and the rest run, so the
    application starts anyway (the site works without a webhook) and still releases its
    resources on exit. If the start or the stop is aborted all the same, what is left of the
    shut-down actions and the closers still runs. The lists are read when the application
    starts and stops, so a closer registered later (an engine created on first use) is still
    called.
    """

    @asynccontextmanager
    async def run(_: FastAPI) -> AsyncIterator[None]:
        try:
            await _run_each(startup, "Start-up")
            yield
        finally:
            try:
                await _run_each(reversed(shutdown), "Shut-down")
            finally:
                for close in (close for group in closers for close in group):
                    close()

    return run


async def _run_each(actions: Iterable[Action], stage: str) -> None:
    """Run every action in order; one that raises is logged and the next one runs."""
    for action in actions:
        try:
            await run_action(action)
        except Exception as error:
            # The message may hold a secret (a bot token in a URL): the class only.
            logger.error("%s action %s failed: %s", stage, _name(action), type(error).__name__)


def _name(action: Action) -> str:
    """``module.qualname`` of a start-up or shut-down action, to find its slice in the log."""
    module = getattr(action, "__module__", None) or "?"
    return f"{module}.{getattr(action, '__qualname__', type(action).__qualname__)}"


def _event(settings: Settings) -> EventValues | None:
    """Values of the webinar's date for the texts; none in the redirect stub (no ``EVENT_*``)."""
    if settings.event_start is None or settings.event_end is None:
        return None
    return event_values(settings.event_start, settings.event_end)


def create_app(
    settings: Settings | None = None,
    *,
    db_probe: DatabaseProbe | None = None,
    docs_dir: Path | None = None,
    overrides: Iterable[Override] = (),
) -> FastAPI:
    """Build the application; read settings from the environment unless given.

    Ports that are not passed in get their real adapters; tests pass fakes: ``db_probe`` and
    ``overrides`` of services (``app.services``). Every slice in ``app.slices`` is installed
    (not in the redirect stub). Nothing here builds a client or reaches the network: services
    are built on first use, and the engine connects lazily.
    """
    settings = settings if settings is not None else load_settings()
    docs = docs_dir if docs_dir is not None else DOCS_DIR
    legal = load_legal_texts(docs)
    page_texts = load_page_texts(
        docs,
        event=_event(settings),
        lesson_start=settings.lesson_start,
        lesson_end=settings.lesson_end,
    )
    page_meta = None if settings.redirect_base_url else build_page_meta(page_texts, settings)
    configure_logging()

    closers: list[Callable[[], None]] = []
    engines: list[Engine] = []

    def engine() -> Engine:
        if not engines:
            engines.append(make_engine(settings.database_url.get_secret_value()))
            closers.append(engines[0].dispose)
        return engines[0]

    if db_probe is None:
        db_probe = SqlDatabaseProbe(engine())

    services = Services(overrides)
    services.provide(CLOCK, SystemClock)
    services.provide(PARTICIPANTS, lambda: SqlParticipantStore(engine()))
    services.provide(LINK_TOKENS, lambda: SqlLinkTokenStore(engine()))
    setup = SliceSetup(settings=settings, services=services, _engine=engine)
    if not settings.redirect_base_url:
        for found in discover_slices(slices):
            found.install(setup.for_slice(found.name))

    app = FastAPI(
        title="Application",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan(setup.startup, setup.shutdown, setup.closers, closers),
    )
    templates = make_templates()
    templates.env.globals.update(setup.template_globals)
    app.state.container = Container(
        settings=settings,
        db_probe=db_probe,
        legal=legal,
        templates=templates,
        page_texts=page_texts,
        page_meta=page_meta,
        services=services,
    )
    if not settings.indexing_enabled:

        @app.middleware("http")
        async def noindex_everything(
            request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            response = await call_next(request)
            response.headers.setdefault("X-Robots-Tag", NOINDEX["X-Robots-Tag"])
            return response

    for middleware in setup.middleware:
        app.add_middleware(middleware.cls, *middleware.args, **middleware.kwargs)
    # Outside the slices' middleware: their early answers on a token path get it too.
    app.add_middleware(NoReferrerOnTokenPaths)
    if settings.redirect_base_url:
        # Added last, so it wraps every other middleware and route.
        app.add_middleware(
            RedirectEverything,
            base_url=settings.redirect_base_url,
            extra_headers=None if settings.indexing_enabled else NOINDEX,
        )
    for router in discover_routers(routers):
        app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
