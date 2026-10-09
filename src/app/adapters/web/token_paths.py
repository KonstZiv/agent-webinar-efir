"""Paths that carry a secret token: one definition for every protection of the token.

A route such as ``/unsubscribe/{token}`` puts a permission into its address. Under each prefix
listed here the access log masks the next path segment and Google Analytics is not loaded
(it would receive the address). Add the prefix together with the route; the template has no
such routes yet.
"""

TOKEN_PATH_PREFIXES: tuple[str, ...] = ()


def carries_token(path: str, prefixes: tuple[str, ...] | None = None) -> bool:
    """Whether ``path`` lies under one of ``prefixes`` (by default ``TOKEN_PATH_PREFIXES``).

    >>> carries_token("/t/abc", ("/t/",)), carries_token("/privacy", ("/t/",))
    (True, False)
    """
    chosen = TOKEN_PATH_PREFIXES if prefixes is None else prefixes
    return any(path.startswith(prefix) for prefix in chosen)
