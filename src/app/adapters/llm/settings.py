"""Settings of the slice «llm»: variables ``LLM_*``, defaults here (docs/requirements.md, 12).

``LLM_ENABLED`` and ``ANTHROPIC_API_KEY`` belong to the shared ``Settings``; the rest is the
slice's own and is not in docs/env.example (operator's decision), so every value has a default.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LlmSettings(BaseSettings):
    """``LLM_MODEL``, ``LLM_MAX_CHARS``, ``LLM_PER_HOUR``, ``LLM_MAX_TOKENS``, ``LLM_TIMEOUT``."""

    model_config = SettingsConfigDict(
        env_prefix="LLM_", env_ignore_empty=True, hide_input_in_errors=True, extra="ignore"
    )

    model: str = Field("claude-sonnet-5-5", min_length=1, max_length=100)
    max_chars: int = Field(1000, gt=0, le=4000)  # the longest message to the bot
    per_hour: int = Field(20, gt=0)  # questions of one person per hour
    max_tokens: int = Field(1000, gt=0, le=4096)  # the longest answer, thinking included
    timeout: float = Field(30.0, gt=0, le=120)  # seconds to wait for the API
