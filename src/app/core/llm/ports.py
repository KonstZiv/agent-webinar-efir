"""Ports of the LLM draft: the language model and the place the classification is kept."""

from dataclasses import dataclass
from typing import Protocol

from app.core.llm.classification import Classification


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """What is asked: the instruction, the person's message (already framed), the token limit."""

    system: str
    user_message: str
    max_tokens: int


@dataclass(frozen=True, slots=True)
class ModelReply:
    """What came back: the input of the result tool, or ``None`` when it was not called.

    ``truncated`` is a reply cut by the token limit: it is not a result, whatever it holds.
    """

    tool_input: dict[str, object] | None
    truncated: bool = False
    input_tokens: int = 0
    output_tokens: int = 0


class ModelUnavailable(Exception):
    """The model gave no reply. Carries what is safe to log: the class of the failure, the HTTP
    code and the type of the error of the API (``invalid_request_error``); never a message,
    which may hold the text of the request."""

    def __init__(self, cause: str, status: int | None = None, error_type: str | None = None):
        super().__init__(cause)
        self.cause = cause
        self.status = status
        self.error_type = error_type


class LanguageModel(Protocol):
    def complete(self, request: ModelRequest) -> ModelReply:
        """Ask the model; ``ModelUnavailable`` when it cannot answer."""
        ...


class ClassificationStore(Protocol):
    def save(self, telegram_user_id: int, classification: Classification) -> bool:
        """Keep the classification for the participant linked to this Telegram.

        ``False`` when nobody is linked to it: the classification is then not kept.
        """
        ...
