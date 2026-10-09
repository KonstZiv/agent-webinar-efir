"""Application settings read from environment variables (see docs/env.example).

Errors never echo setting values: an invalid ``REDIRECT_BASE_URL`` must not print the
database URL or any other secret that happens to be set.
"""

import ipaddress
import re
from typing import Annotated
from urllib.parse import SplitResult, urlsplit

from pydantic import AfterValidator, Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from pydantic_settings import SettingsError as SettingsSourceError

COMMIT_SHORT_LENGTH = 7
DRIVER_SCHEME = "postgresql+psycopg"
_POSTGRES_SCHEMES = frozenset({"postgres", "postgresql", DRIVER_SCHEME})
_WEB_SCHEMES = frozenset({"http", "https"})
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")

_ENV_CONFIG = SettingsConfigDict(
    env_ignore_empty=True,  # an empty variable counts as unset
    hide_input_in_errors=True,
    extra="ignore",
)


class ConfigError(Exception):
    """Settings are missing or invalid; the message names variables, never their values."""


def _has_unsafe_characters(value: str) -> bool:
    return any(char.isspace() or not char.isprintable() for char in value)


def _split_url(value: str, error: ValueError) -> SplitResult:
    """Split a URL, turning every parsing problem into ``error`` (which carries no value)."""
    if _has_unsafe_characters(value):
        raise error
    try:
        parts = urlsplit(value)
        _ = parts.port  # raises on a non-numeric port; its message would echo the value
    except ValueError:
        raise error from None
    return parts


def normalize_database_url(url: str) -> str:
    """Validate a PostgreSQL URL and point it at the psycopg 3 driver.

    The error message never contains the URL: it may hold a password.

    >>> normalize_database_url("postgres://user@db.example.com:5432/app")
    'postgresql+psycopg://user@db.example.com:5432/app'
    """
    error = ValueError("must be a PostgreSQL URL like postgresql://user:password@host:5432/db")
    parts = _split_url(url, error)
    if parts.scheme not in _POSTGRES_SCHEMES or not parts.hostname or not parts.path.strip("/"):
        raise error
    return f"{DRIVER_SCHEME}://{url.split('://', 1)[1]}"


def _database_url(value: SecretStr) -> SecretStr:
    return SecretStr(normalize_database_url(value.get_secret_value()))


def _ascii_host(host: str) -> str | None:
    """``host`` as ``urlsplit`` gives it, written as ASCII DNS labels or an IP address.

    ``None`` when it is neither: commas, backslashes, underscores, empty labels.

    >>> _ascii_host("пошта.укр"), _ascii_host("::1"), _ascii_host("a,b.example.com")
    ('xn--80a1acn3a.xn--j1amh', '[::1]', None)
    """
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return f"[{address}]" if address.version == 6 else str(address)
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    labels = ascii_host.split(".")
    return ascii_host if all(_DNS_LABEL.fullmatch(label) for label in labels) else None


def _site_address(value: str) -> str:
    """A site root such as ``https://site.example.com``; a trailing slash is dropped.

    The host comes out in lower case and ASCII (punycode): a ``Location`` header cannot
    carry other characters.

    >>> _site_address("https://Site.Example.com/")
    'https://site.example.com'
    >>> _site_address("https://site.example.com/?x=1")
    Traceback (most recent call last):
    ...
    ValueError: must be a site root: http(s) and host only, no path, query, fragment or login
    """
    if not value:
        return value
    error = ValueError(
        "must be a site root: http(s) and host only, no path, query, fragment or login"
    )
    parts = _split_url(value, error)
    if (
        parts.scheme not in _WEB_SCHEMES
        or not parts.hostname
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
        or "?" in value
        or "#" in value
        or parts.username is not None
        or parts.netloc.endswith(":")  # an empty port
        or "\\" in parts.netloc
        or "%" in parts.netloc
    ):
        raise error
    host = _ascii_host(parts.hostname)
    if host is None:
        raise error
    port = f":{parts.port}" if parts.port is not None else ""
    return f"{parts.scheme}://{host}{port}"


DatabaseUrl = Annotated[SecretStr, AfterValidator(_database_url)]
SiteAddress = Annotated[str, AfterValidator(_site_address)]


class DatabaseSettings(BaseSettings):
    """The only setting Alembic needs."""

    model_config = _ENV_CONFIG

    database_url: DatabaseUrl


class Settings(BaseSettings):
    """All settings of the application; field ``name`` is read from the variable ``NAME``.

    Only ``DATABASE_URL`` is required: the redirect stub runs with it and
    ``REDIRECT_BASE_URL`` alone. Variables of adapters that no route uses yet are optional.
    """

    model_config = _ENV_CONFIG

    database_url: DatabaseUrl
    redirect_base_url: SiteAddress = ""  # non-empty: every request but /healthz gets a 307
    indexing_enabled: bool = False  # off until launch: every response is noindex
    ga4_measurement_id: str = ""  # empty: no analytics and no automatic cookie banner
    turnstile_site_key: str = ""
    turnstile_secret_key: SecretStr | None = None
    turnstile_allowed_hostnames: Annotated[tuple[str, ...], NoDecode] = Field(default=())
    railway_git_commit_sha: str = ""

    @field_validator("turnstile_allowed_hostnames", mode="before")
    @classmethod
    def _split_hostnames(cls, value: object) -> object:
        if isinstance(value, str):
            # DNS names ignore case; Turnstile reports them in lower case.
            return tuple(item.strip().lower() for item in value.split(",") if item.strip())
        return value

    @property
    def commit_short(self) -> str:
        """Short commit hash of the deployed build, or an empty string."""
        return self.railway_git_commit_sha[:COMMIT_SHORT_LENGTH]


def _describe(error: ValidationError) -> str:
    lines = []
    for item in error.errors(include_url=False, include_input=False, include_context=False):
        name = ".".join(str(part) for part in item["loc"][:1]).upper()
        reason = "required but not set" if item["type"] == "missing" else item["msg"]
        lines.append(f"  - {name}: {reason}" if name else f"  - {reason}")
    return "\n".join(lines)


def _load[T: BaseSettings](cls: type[T]) -> T:
    try:
        return cls()
    except ValidationError as error:
        message = f"Invalid configuration (environment variables):\n{_describe(error)}"
    except SettingsSourceError:
        message = "Invalid configuration: an environment variable could not be parsed"
    raise ConfigError(message) from None


def load_settings() -> Settings:
    """Read and validate all settings; raise ``ConfigError`` without values on failure."""
    return _load(Settings)


def load_database_settings() -> DatabaseSettings:
    """Read only ``DATABASE_URL`` (for Alembic)."""
    return _load(DatabaseSettings)
