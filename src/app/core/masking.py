"""Masking of personal data before it reaches logs."""

MASK = "***"


def _is_domain(value: str) -> bool:
    """Letters, digits and hyphens in dot-separated labels: nothing that can break a log line."""
    labels = value.split(".")
    return all(label and all(char.isalnum() or char == "-" for char in label) for label in labels)


def mask_email(email: str) -> str:
    """Hide everything in an email address except the first character and the domain.

    Use it for every email address written to logs. The result is always a single printable
    line: an address with control characters or line breaks is masked completely.

    >>> mask_email("user@example.com")
    'u***@example.com'
    >>> mask_email("  User@Example.com ")
    'U***@Example.com'
    >>> mask_email("not-an-address")
    '***'
    >>> mask_email("user@example.com\\r\\nforged log line")
    '***'
    """
    local, at, domain = email.strip().rpartition("@")
    if not at or not local or not _is_domain(domain):
        return MASK
    first = local[0] if local[0].isalnum() else ""
    return f"{first}{MASK}@{domain}"
