"""Secret tokens in paths stay out of the uvicorn access log (see ``token_paths``).

uvicorn logs every request as ``'%s - "%s %s HTTP/%s" %d'`` with the path in the third
argument; a token in the path may be a permission to change data.
"""

import logging
import re

from app.adapters.web import token_paths

ACCESS_LOGGER = "uvicorn.access"
MASK = "***"
_PATH_ARGUMENT = 2


class MaskTokenPaths(logging.Filter):
    """Replace the segment after a token prefix in access log records; others pass unchanged."""

    def __init__(self, prefixes: tuple[str, ...]) -> None:
        super().__init__()
        self.prefixes = prefixes
        alternatives = "|".join(re.escape(prefix) for prefix in prefixes)
        self._token_path = re.compile(rf"^({alternatives})[^/?]*") if prefixes else None

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if self._token_path is not None and isinstance(args, tuple) and len(args) > _PATH_ARGUMENT:
            path = args[_PATH_ARGUMENT]
            if isinstance(path, str) and self._token_path.match(path):
                masked = self._token_path.sub(rf"\g<1>{MASK}", path, count=1)
                record.args = (*args[:_PATH_ARGUMENT], masked, *args[_PATH_ARGUMENT + 1 :])
        return True


def install_access_log_filter(prefixes: tuple[str, ...] | None = None) -> None:
    """Give uvicorn's access logger exactly one filter, for ``prefixes``.

    ``prefixes`` defaults to ``token_paths.TOKEN_PATH_PREFIXES`` as it is at the time of the
    call. A filter installed earlier for other prefixes is replaced, not kept.
    """
    chosen = token_paths.TOKEN_PATH_PREFIXES if prefixes is None else prefixes
    logger = logging.getLogger(ACCESS_LOGGER)
    installed = [item for item in logger.filters if isinstance(item, MaskTokenPaths)]
    if [item.prefixes for item in installed] == [chosen]:
        return
    for item in installed:
        logger.removeFilter(item)
    logger.addFilter(MaskTokenPaths(chosen))
