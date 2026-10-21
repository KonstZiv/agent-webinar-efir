"""The shared fakes satisfy the ports (checked by mypy) and behave as their docstrings say."""

import uuid
from pathlib import Path

import pytest
from mypy import api as mypy_api

from app.core.entities import ChatMember, OutgoingEmail
from app.core.ports import MessengerUnavailable
from app.main import create_app
from app.services import CLOCK, EMAIL_SENDER, HUMAN_CHECK, MESSENGER
from tests.conftest import REPO_ROOT, SettingsFactory
from tests.fakes import (
    FAILED,
    FakeDatabaseProbe,
    FakeEmailSender,
    FakeMessenger,
    fake_overrides,
)

CONFORMANCE = """\
from app.core.ports import Clock, DatabaseProbe, EmailSender, HumanCheck, Messenger
from tests.fakes import (
    FakeDatabaseProbe, FakeEmailSender, FakeHumanCheck, FakeMessenger, FixedClock,
)

probe: DatabaseProbe = FakeDatabaseProbe()
clock: Clock = FixedClock()
sender: EmailSender = FakeEmailSender()
check: HumanCheck = FakeHumanCheck()
messenger: Messenger = FakeMessenger()
"""
MESSAGE = OutgoingEmail("Sender <s@example.com>", "to@example.com", "subject", "<p>x</p>", "x")


def test_fakes_satisfy_the_ports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = tmp_path / "conformance.py"
    module.write_text(CONFORMANCE, encoding="utf-8")
    monkeypatch.setenv("MYPYPATH", str(REPO_ROOT / "src"))  # the sources, not the installed copy

    stdout, stderr, status = mypy_api.run(
        [str(module), "--config-file", str(REPO_ROOT / "pyproject.toml"), "--no-incremental"]
    )

    assert status == 0, stdout + stderr


def test_email_sender_answers_as_scripted_then_accepts() -> None:
    sender = FakeEmailSender(FAILED)
    key = uuid.uuid4()

    assert sender.send(MESSAGE, key) == FAILED
    assert sender.send(MESSAGE, key).provider_id == "fake-2"  # type: ignore[union-attr]
    assert [sent_key for _, sent_key in sender.sent] == [key, key]


def test_messenger_records_and_can_fail() -> None:
    messenger = FakeMessenger(members={7: ChatMember("member")})

    messenger.send_message(7, "hi")
    assert messenger.channel_member("@channel", 7) == ChatMember("member")
    assert messenger.channel_member("@channel", 8) == ChatMember("left")
    assert [message.text for message in messenger.sent] == ["hi"]

    messenger.unavailable = True
    with pytest.raises(MessengerUnavailable):
        messenger.send_message(7, "hi")


def test_fake_overrides_cover_every_outside_port(make_settings: SettingsFactory) -> None:
    sender = FakeEmailSender()
    app = create_app(
        make_settings(), db_probe=FakeDatabaseProbe(), overrides=fake_overrides(email_sender=sender)
    )
    services = app.state.container.services

    assert services.get(EMAIL_SENDER) is sender
    assert all(services.find(key) is not None for key in (CLOCK, HUMAN_CHECK, MESSENGER))
