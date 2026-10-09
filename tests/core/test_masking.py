import pytest

from app.core.masking import mask_email


@pytest.mark.parametrize(
    ("raw", "masked"),
    [
        ("user@example.com", "u***@example.com"),
        ("  user@example.com  ", "u***@example.com"),
        ("u@example.com", "u***@example.com"),
        ("First.Last+tag@Example.COM", "F***@Example.COM"),
        ("a@b@example.com", "a***@example.com"),
        ("", "***"),
        ("not-an-address", "***"),
        ("@example.com", "***"),
        ("user@", "***"),
    ],
)
def test_mask_email(raw: str, masked: str) -> None:
    assert mask_email(raw) == masked


def test_mask_email_never_contains_local_part_tail() -> None:
    assert "ser" not in mask_email("user@example.com")


# Nothing from the address may forge or break a log line.
HOSTILE_INPUTS = [
    "user@example.com\r\nINFO forged log line",
    "user@exa\nmple.com",
    "user@example.com\x1b[31m",
    "user@exam ple.com",
    "\nuser@example.com",
    "\x00@example.com",
    "user@example.com\u2028forged",
]


@pytest.mark.parametrize("raw", HOSTILE_INPUTS)
def test_mask_email_output_is_a_single_printable_line(raw: str) -> None:
    masked = mask_email(raw)

    assert masked.isprintable()
    assert "forged" not in masked


@pytest.mark.parametrize(
    ("raw", "masked"),
    [
        ("user@example.com\r\nINFO forged log line", "***"),
        ("user@exa\nmple.com", "***"),
        ("\x00user@example.com", "***@example.com"),
        ("user@пошта.test", "u***@пошта.test"),
    ],
)
def test_mask_email_hostile_cases(raw: str, masked: str) -> None:
    assert mask_email(raw) == masked
