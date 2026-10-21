"""The foundation's pages without the partials of slices, for the tests of the foundation alone.

The fallback page of ``/`` includes ``_form.html`` and ``_counters.html`` by name and skips the
missing ones (docs/requirements.md, section 12); a partial brings its own scripts. A test of the
foundation's page hides them, so it keeps checking the foundation once the slices add them.
"""

from collections.abc import Callable

from fastapi import FastAPI
from jinja2 import BaseLoader, Environment, TemplateNotFound

SLICE_PARTIALS = frozenset({"_form.html", "_counters.html"})


class HidingLoader(BaseLoader):
    """Finds what ``loader`` finds, except the templates named in ``hidden``."""

    def __init__(self, loader: BaseLoader, hidden: frozenset[str]) -> None:
        self.loader = loader
        self.hidden = hidden

    def get_source(
        self, environment: Environment, template: str
    ) -> tuple[str, str | None, Callable[[], bool] | None]:
        if template in self.hidden:
            raise TemplateNotFound(template)
        return self.loader.get_source(environment, template)

    def list_templates(self) -> list[str]:
        return [name for name in self.loader.list_templates() if name not in self.hidden]


def without_slice_partials(app: FastAPI) -> FastAPI:
    """Hide the partials of slices from the application's templates; return ``app``."""
    env = app.state.container.templates.env
    env.loader = HidingLoader(env.loader, SLICE_PARTIALS)
    return app
