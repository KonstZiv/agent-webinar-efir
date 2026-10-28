"""The language model on Claude API (``anthropic``).

Facts of the model ``claude-sonnet-5-5`` the request depends on:

- ``tool_choice`` of ``tool`` and ``any`` is refused with 400; only ``auto`` (the default) and
  ``none`` are allowed. The structured result is a tool the instruction asks to always call,
  so a reply without the call is an ordinary case and not an error.
- Adaptive thinking is on by default and spends ``max_tokens``; ``between_tools`` keeps short
  answers short. ``disabled`` and ``enabled`` with a budget are refused with 400.
- A reply may hold blocks of ``thinking`` before ``text`` and ``tool_use``: the tool call is
  looked up by type and name, never by index. ``stop_reason`` ``max_tokens`` is a cut reply.

A failure becomes ``ModelUnavailable`` with the class, the HTTP code and the type of the error
of the API when it has the shape of a type name; the message of the SDK may hold the request.
"""

import re

import anthropic
from anthropic.types import ToolParam

from app.core.llm.ports import ModelReply, ModelRequest, ModelUnavailable
from app.core.llm.prompt import TOOL_DESCRIPTION, TOOL_NAME, TOOL_SCHEMA

_ERROR_TYPE = re.compile(r"[a-z_]{1,64}")


def make_client(api_key: str, timeout: float) -> anthropic.Anthropic:
    """The client; no retries: a person waits on the webhook, and a retry doubles the wait."""
    return anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=0)


class ClaudeModel:
    def __init__(self, client: anthropic.Anthropic, *, model: str) -> None:
        self._client = client
        self._model = model
        self._tool = ToolParam(
            name=TOOL_NAME,
            description=TOOL_DESCRIPTION,
            input_schema=TOOL_SCHEMA,
        )

    def complete(self, request: ModelRequest) -> ModelReply:
        try:
            message = self._client.messages.create(
                model=self._model,
                max_tokens=request.max_tokens,
                system=request.system,
                messages=[{"role": "user", "content": request.user_message}],
                tools=[self._tool],
                tool_choice={"type": "auto"},
                thinking={"type": "between_tools"},
            )
        except anthropic.APIStatusError as error:
            raise ModelUnavailable(
                type(error).__name__, error.status_code, _error_type(error.type)
            ) from None
        except anthropic.APIError as error:  # no response: a timeout, a lost connection
            raise ModelUnavailable(type(error).__name__) from None
        truncated = message.stop_reason == "max_tokens"
        tool_input = None
        if not truncated:
            for block in message.content:
                if block.type == "tool_use" and block.name == TOOL_NAME:
                    tool_input = dict(block.input)
                    break
        return ModelReply(
            tool_input,
            truncated=truncated,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )


def _error_type(value: object) -> str | None:
    return value if isinstance(value, str) and _ERROR_TYPE.fullmatch(value) else None
