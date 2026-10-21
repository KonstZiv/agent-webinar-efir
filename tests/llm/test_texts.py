"""The texts of the draft are docs/copy.md, section 12.4, word for word; the settings' defaults."""

import pytest
from pydantic import ValidationError

from app.adapters.llm.settings import LlmSettings
from app.core.llm import replies
from tests.llm.helpers import failure, llm_copy, refusal, too_long, too_many


def test_the_table_has_the_four_situations() -> None:
    assert len(llm_copy()) == 4


def test_the_texts_are_those_of_copy_md() -> None:
    assert refusal() == replies.REFUSAL
    assert too_long(123) == replies.TOO_LONG.format(max_chars=123)
    assert too_many() == replies.TOO_MANY
    assert failure() == replies.FAILURE


def test_the_defaults_of_the_slice_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LLM_MODEL", "LLM_MAX_CHARS", "LLM_PER_HOUR", "LLM_MAX_TOKENS", "LLM_TIMEOUT"):
        monkeypatch.delenv(name, raising=False)

    settings = LlmSettings()

    assert settings.model == "claude-sonnet-5-5"
    assert settings.max_chars > 0
    assert settings.per_hour > 0
    assert settings.max_tokens > 0
    assert settings.timeout > 0


def test_the_slice_settings_read_the_llm_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "claude-test")
    monkeypatch.setenv("LLM_MAX_CHARS", "77")
    monkeypatch.setenv("LLM_ENABLED", "true")  # the shared Settings own it: ignored here

    settings = LlmSettings()

    assert (settings.model, settings.max_chars) == ("claude-test", 77)


@pytest.mark.parametrize("name", ["LLM_MAX_CHARS", "LLM_PER_HOUR", "LLM_MAX_TOKENS", "LLM_TIMEOUT"])
@pytest.mark.parametrize("value", ["0", "-1"])
def test_a_limit_must_be_positive(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        LlmSettings()
