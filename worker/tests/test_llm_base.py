from __future__ import annotations

from it2pr_worker.llm.base import LLMResponse, Message, ToolCall, ToolSpec, Usage


def test_message_round_trip() -> None:
    msg = Message(role="user", content="hello")

    assert msg.role == "user"
    assert msg.content == "hello"
    assert msg.name is None
    assert msg.tool_call_id is None


def test_message_with_tool_call_id() -> None:
    msg = Message(role="tool", content="result", tool_call_id="call_1")

    assert msg.tool_call_id == "call_1"


def test_tool_spec_round_trip() -> None:
    spec = ToolSpec(
        name="run_tests",
        description="Run the test suite",
        parameters={"type": "object", "properties": {}},
    )

    assert spec.name == "run_tests"
    assert spec.parameters["type"] == "object"


def test_tool_call_round_trip() -> None:
    call = ToolCall(id="call_1", name="run_tests", arguments={"path": "."})

    assert call.id == "call_1"
    assert call.arguments == {"path": "."}


def test_usage_defaults_cost_to_none() -> None:
    usage = Usage(prompt_tokens=10, completion_tokens=5)

    assert usage.cost_usd is None


def test_usage_with_cost() -> None:
    usage = Usage(prompt_tokens=10, completion_tokens=5, cost_usd=0.0012)

    assert usage.cost_usd == 0.0012


def test_llm_response_defaults() -> None:
    response = LLMResponse(content="hi")

    assert response.content == "hi"
    assert response.tool_calls == []
    assert response.usage.prompt_tokens == 0
    assert response.raw == {}


def test_llm_response_with_tool_calls() -> None:
    call = ToolCall(id="call_1", name="edit_file", arguments={})
    response = LLMResponse(
        content=None,
        tool_calls=[call],
        usage=Usage(prompt_tokens=1, completion_tokens=1),
        raw={"id": "gen-1"},
    )

    assert response.content is None
    assert response.tool_calls == [call]
    assert response.raw["id"] == "gen-1"
