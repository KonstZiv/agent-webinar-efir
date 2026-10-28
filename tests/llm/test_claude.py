"""The adapter of Claude API with a stand-in client: the request, the reading, the errors."""

import anthropic
import httpx2
import pytest

from app.adapters.llm.claude import ClaudeModel
from app.core.llm.ports import ModelRequest, ModelUnavailable
from tests.llm.helpers import FakeClient, api_message, block

REQUEST = ModelRequest(system="Instruction", user_message="Question", max_tokens=321)
TOOL_INPUT = {
    "answer": "Так.",
    "in_knowledge_base": True,
    "level": "beginner",
    "intent": "browsing",
}


def model(client: FakeClient) -> ClaudeModel:
    return ClaudeModel(client, model="claude-sonnet-5-5")  # type: ignore[arg-type]


def status_error(
    status: int, body: object, kind: type[anthropic.APIStatusError]
) -> anthropic.APIStatusError:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(status, request=request, json=body)
    return kind("the message may carry the text of the request", response=response, body=body)  # type: ignore[arg-type]


def test_the_request_has_no_forced_tool_and_thinks_between_tools() -> None:
    client = FakeClient(api_message(block("tool_use", name="reply_to_visitor", input=TOOL_INPUT)))

    model(client).complete(REQUEST)

    (call,) = client.calls
    assert call["tool_choice"] in ({"type": "auto"}, None) or "tool_choice" not in call
    assert call["thinking"] == {"type": "between_tools"}
    assert call["model"] == "claude-sonnet-5-5"
    assert call["max_tokens"] == 321
    assert call["system"] == "Instruction"
    assert call["messages"] == [{"role": "user", "content": "Question"}]
    assert [tool["name"] for tool in call["tools"]] == ["reply_to_visitor"]


def test_the_tool_describes_the_answer_the_level_and_the_intent() -> None:
    client = FakeClient(api_message(block("tool_use", name="reply_to_visitor", input=TOOL_INPUT)))

    model(client).complete(REQUEST)

    schema = client.calls[0]["tools"][0]["input_schema"]
    properties = schema["properties"]
    assert set(properties) == {"answer", "in_knowledge_base", "level", "intent"}
    assert properties["level"]["enum"] == ["beginner", "experienced", "unknown"]
    assert properties["intent"]["enum"] == ["ready_to_enroll", "considering", "browsing", "unknown"]
    assert set(schema["required"]) == set(properties)


def test_the_tool_call_is_found_by_type_after_a_thinking_block() -> None:
    message = api_message(
        block("thinking", thinking="…", signature="x"),
        block("text", text="Сторонній текст"),
        block("tool_use", name="reply_to_visitor", input=TOOL_INPUT),
        input_tokens=111,
        output_tokens=22,
    )

    reply = model(FakeClient(message)).complete(REQUEST)

    assert reply.tool_input == TOOL_INPUT
    assert (reply.input_tokens, reply.output_tokens, reply.truncated) == (111, 22, False)


def test_a_reply_without_a_tool_call_has_no_result() -> None:
    message = api_message(
        block("thinking", thinking="…", signature="x"),
        block("text", text="Ось відповідь без інструмента"),
        stop_reason="end_turn",
    )

    reply = model(FakeClient(message)).complete(REQUEST)

    assert reply.tool_input is None
    assert reply.truncated is False


def test_another_tool_is_not_the_result() -> None:
    message = api_message(block("tool_use", name="something_else", input=TOOL_INPUT))

    assert model(FakeClient(message)).complete(REQUEST).tool_input is None


def test_a_cut_reply_is_marked_and_has_no_result() -> None:
    message = api_message(
        block("tool_use", name="reply_to_visitor", input={"answer": "Обсяг"}),
        stop_reason="max_tokens",
    )

    reply = model(FakeClient(message)).complete(REQUEST)

    assert reply.truncated is True
    assert reply.tool_input is None


def test_a_status_error_keeps_the_class_the_code_and_the_type_of_the_error_only() -> None:
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": "secret text"}}
    client = FakeClient(status_error(400, body, anthropic.BadRequestError))

    with pytest.raises(ModelUnavailable) as caught:
        model(client).complete(REQUEST)

    error = caught.value
    assert (error.cause, error.status, error.error_type) == (
        "BadRequestError",
        400,
        "invalid_request_error",
    )
    assert "secret" not in repr(error) + str(error)
    assert error.__cause__ is None
    assert error.__suppress_context__


def test_an_odd_type_of_error_is_not_kept() -> None:
    body = {"type": "error", "error": {"type": "bad type with the user's text", "message": "x"}}
    client = FakeClient(status_error(500, body, anthropic.InternalServerError))

    with pytest.raises(ModelUnavailable) as caught:
        model(client).complete(REQUEST)

    assert (caught.value.status, caught.value.error_type) == (500, None)


def test_a_failure_without_a_response_has_the_class_only() -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    client = FakeClient(anthropic.APITimeoutError(request=request))

    with pytest.raises(ModelUnavailable) as caught:
        model(client).complete(REQUEST)

    assert (caught.value.cause, caught.value.status, caught.value.error_type) == (
        "APITimeoutError",
        None,
        None,
    )
