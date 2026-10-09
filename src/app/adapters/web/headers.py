"""Response headers shared by routes."""

NOINDEX = {"X-Robots-Tag": "noindex"}
# Service responses: never cached (their content may change at any moment), never indexed.
SERVICE = {"Cache-Control": "no-store", **NOINDEX}
