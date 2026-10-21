"""Polls of the counters stay out of the uvicorn access log (docs/requirements.md, section 15).

Hundreds of viewers ask for ``/counters`` every 15 seconds. The operator reads the log in
Railway when something goes wrong, live on screen: a line per poll would bury the useful ones
and show each viewer's IP address every 15 seconds. The foundation's
``install_access_log_filter`` replaces only its own filter, so this one stays.
"""

import logging

from app.adapters.extras.view import COUNTERS_PATH
from app.adapters.web.access_log import ACCESS_LOGGER

# uvicorn logs ``'%s - "%s %s HTTP/%s" %d'``: client, method, path with query, version, status.
_PATH_ARGUMENT = 2


class DropCounterPolls(logging.Filter):
    """Drop access records of ``/counters``, whatever the query, method or status."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) > _PATH_ARGUMENT:
            path = args[_PATH_ARGUMENT]
            if isinstance(path, str) and path.partition("?")[0] == COUNTERS_PATH:
                return False
        return True


def install_counter_polls_filter() -> None:
    """Give uvicorn's access logger exactly one ``DropCounterPolls``."""
    access = logging.getLogger(ACCESS_LOGGER)
    if not any(isinstance(item, DropCounterPolls) for item in access.filters):
        access.addFilter(DropCounterPolls())
