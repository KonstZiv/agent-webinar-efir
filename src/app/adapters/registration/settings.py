"""Settings of normal operation that the slice reads (docs/requirements.md, section 14)."""


def required[T](value: T | None, name: str) -> T:
    """A value of normal operation; ``Settings`` has already made it required.

    >>> required("value", "NAME")
    'value'
    >>> required(None, "EVENT_START")
    Traceback (most recent call last):
    ...
    RuntimeError: EVENT_START is required in normal operation
    """
    if value is None:
        raise RuntimeError(f"{name} is required in normal operation")
    return value
