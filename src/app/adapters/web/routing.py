"""Automatic discovery of route modules: no manual list in ``main``."""

import importlib
import pkgutil
from types import ModuleType

from fastapi import APIRouter


def discover_routers(package: ModuleType) -> list[APIRouter]:
    """Import every module of ``package`` and return its ``router``, ordered by module name.

    A module without an ``APIRouter`` named ``router`` is a mistake, not something to skip.
    """
    found = []
    for module_info in sorted(pkgutil.iter_modules(package.__path__), key=lambda m: m.name):
        module = importlib.import_module(f"{package.__name__}.{module_info.name}")
        router = getattr(module, "router", None)
        if not isinstance(router, APIRouter):
            raise TypeError(f"Route module {module.__name__} must define `router: APIRouter`")
        found.append(router)
    return found
