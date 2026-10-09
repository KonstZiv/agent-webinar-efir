"""Composition root: ``create_app`` builds the application from settings and adapters.

Run with ``uvicorn app.main:create_app --factory``; there is no module-level app, so
importing this module needs no environment variables.
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

from app.adapters.content.legal import load_legal_texts
from app.adapters.db.engine import make_engine
from app.adapters.db.probe import SqlDatabaseProbe
from app.adapters.web import routers
from app.adapters.web.access_log import install_access_log_filter
from app.adapters.web.dependencies import STATIC_DIR, Container, make_templates
from app.adapters.web.headers import NOINDEX
from app.adapters.web.redirect import RedirectEverything
from app.adapters.web.routing import discover_routers
from app.core.ports import DatabaseProbe
from app.settings import Settings, load_settings

# Texts live in the repository's docs/; on Railway the working directory is the repository
# root (/app).
DOCS_DIR = Path("docs")

type Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


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


def closing(closers: list[Callable[[], None]]) -> Lifespan:
    """Lifespan that calls every closer, in order, when the application shuts down."""

    @asynccontextmanager
    async def close_adapters(_: FastAPI) -> AsyncIterator[None]:
        yield
        for close in closers:
            close()

    return close_adapters


def create_app(
    settings: Settings | None = None,
    *,
    db_probe: DatabaseProbe | None = None,
    docs_dir: Path | None = None,
) -> FastAPI:
    """Build the application; read settings from the environment unless given.

    Ports that are not passed in get their real adapters; tests pass fakes. Every adapter
    that holds connections registers its ``close`` in ``closers``: the application calls
    them on shutdown.
    """
    settings = settings if settings is not None else load_settings()
    legal = load_legal_texts(docs_dir if docs_dir is not None else DOCS_DIR)
    configure_logging()

    closers: list[Callable[[], None]] = []
    if db_probe is None:
        engine = make_engine(settings.database_url.get_secret_value())
        closers.append(engine.dispose)
        db_probe = SqlDatabaseProbe(engine)

    app = FastAPI(
        title="Application",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=closing(closers) if closers else None,
    )
    app.state.container = Container(
        settings=settings,
        db_probe=db_probe,
        legal=legal,
        templates=make_templates(),
    )
    if not settings.indexing_enabled:

        @app.middleware("http")
        async def noindex_everything(
            request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            response = await call_next(request)
            response.headers.setdefault("X-Robots-Tag", NOINDEX["X-Robots-Tag"])
            return response

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
