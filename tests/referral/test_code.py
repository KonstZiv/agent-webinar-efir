"""The code of a personal link: its alphabet and length."""

from app.core.referral.code import is_valid_code, new_code


def test_new_codes_are_valid_and_differ() -> None:
    codes = {new_code() for _ in range(200)}

    assert len(codes) == 200
    assert all(is_valid_code(code) for code in codes)


def test_damaged_codes_are_not_valid() -> None:
    for code in ("", "a b", "x" * 17, "é", "../a", "a\x00b", None):
        assert not is_valid_code(code)
