"""The ticket: signed, expiring, bound to one address."""

from datetime import UTC, datetime, timedelta

from app.core.quiz.ticket import TERM, make_ticket, read_ticket

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
SECRET = "quiz-secret-0123456789abcdef0123456789"


def test_a_ticket_reads_back_its_address() -> None:
    assert read_ticket(make_ticket("a@example.com", NOW, SECRET), NOW, SECRET) == "a@example.com"


def test_a_ticket_lasts_for_the_term_only() -> None:
    ticket = make_ticket("a@example.com", NOW, SECRET)

    assert read_ticket(ticket, NOW + TERM, SECRET) == "a@example.com"
    assert read_ticket(ticket, NOW + TERM + timedelta(seconds=1), SECRET) is None


def test_another_secret_does_not_read_it() -> None:
    ticket = make_ticket("a@example.com", NOW, SECRET)

    assert read_ticket(ticket, NOW, "other-" + SECRET) is None


def test_the_unsubscribe_token_is_not_a_ticket() -> None:
    assert read_ticket("0" * 32 + "." + "A" * 43, NOW, SECRET) is None
