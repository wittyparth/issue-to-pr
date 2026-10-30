from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from it2pr_worker.llm.anthropic import (
    AnthropicProvider,
    ModelPrice,
    ProviderRequestError,
    _messages_to_anthropic,
)
from it2pr_worker.llm.base import Message, ToolCall, ToolSpec


@dataclass
class _FakeResponse:
    status_code: int
    _body: dict[str, Any]

    def json(self) -> dict[str, Any]:
        return self._body


@dataclass
class _FakeHttpClient:
    response: _FakeResponse
    calls: list[tuple[str, dict[str, Any], dict[str, str]]] = field(default_factory=list)

    def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        self.calls.append((url, json, headers))
        return self.response


def test_system_message_mapped_to_top_level_field() -> None:
    body = {
        "content": [{"type": "text", "text": "ok"}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    http = _FakeHttpClient(response=_FakeResponse(200, body))
    provider = AnthropicProvider(model="claude-3-5-sonnet-20241022", api_key="sk-ant-x", http=http)

    provider.complete(
        [
            Message(role="system", content="You are a helpful coding agent."),
            Message(role="user", content="fix the bug"),
        ]
    )

    _, sent_json, headers = http.calls[0]
    assert sent_json["system"] == "You are a helpful coding agent."
    assert sent_json["messages"] == [{"role": "user", "content": "fix the bug"}]
    assert headers["x-api-key"] == "sk-ant-x"


def test_tools_mapped_to_input_schema() -> None:
    body = {"content": [{"type": "text", "text": "ok"}], "usage": {}}
    http = _FakeHttpClient(response=_FakeResponse(200, body))
    provider = AnthropicProvider(model="claude-3-5-sonnet-20241022", api_key="sk-ant-x", http=http)

    provider.complete(
        [Message(role="user", content="run")],
        tools=[
            ToolSpec(
                name="run_tests",
                description="run the tests",
                parameters={"type": "object", "properties": {}},
            )
        ],
    )

    _, sent_json, _ = http.calls[0]
    assert sent_json["tools"][0]["name"] == "run_tests"
    assert sent_json["tools"][0]["input_schema"] == {"type": "object", "properties": {}}
    assert "parameters" not in sent_json["tools"][0]


def test_tool_use_blocks_parsed_into_tool_calls() -> None:
    body = {
        "content": [
            {"type": "text", "text": "Let me run the tests."},
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "run_tests",
                "input": {"path": "."},
            },
        ],
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }
    http = _FakeHttpClient(response=_FakeResponse(200, body))
    provider = AnthropicProvider(model="claude-3-5-sonnet-20241022", api_key="sk-ant-x", http=http)

    result = provider.complete([Message(role="user", content="run tests")])

    assert result.content == "Let me run the tests."
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "toolu_1"
    assert result.tool_calls[0].name == "run_tests"
    assert result.tool_calls[0].arguments == {"path": "."}


def test_usage_tokens_parsed() -> None:
    body = {
        "content": [{"type": "text", "text": "ok"}],
        "usage": {"input_tokens": 200, "output_tokens": 80},
    }
    http = _FakeHttpClient(response=_FakeResponse(200, body))
    provider = AnthropicProvider(model="claude-3-5-sonnet-20241022", api_key="sk-ant-x", http=http)

    result = provider.complete([Message(role="user", content="hi")])

    assert result.usage.prompt_tokens == 200
    assert result.usage.completion_tokens == 80


def test_cost_computed_from_injected_price_table() -> None:
    body = {
        "content": [{"type": "text", "text": "ok"}],
        "usage": {"input_tokens": 1_000_000, "output_tokens": 1_000_000},
    }
    http = _FakeHttpClient(response=_FakeResponse(200, body))
    price_table = {
        "claude-3-5-sonnet-20241022": ModelPrice(input_per_mtok=3.0, output_per_mtok=15.0)
    }
    provider = AnthropicProvider(
        model="claude-3-5-sonnet-20241022",
        api_key="sk-ant-x",
        http=http,
        price_table=price_table,
    )

    result = provider.complete([Message(role="user", content="hi")])

    assert result.usage.cost_usd == pytest.approx(18.0, abs=1e-9)


def test_cost_none_for_unknown_model() -> None:
    body = {
        "content": [{"type": "text", "text": "ok"}],
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }
    http = _FakeHttpClient(response=_FakeResponse(200, body))
    provider = AnthropicProvider(
        model="some-future-model",
        api_key="sk-ant-x",
        http=http,
        price_table={"claude-3-5-sonnet-20241022": ModelPrice(3.0, 15.0)},
    )

    result = provider.complete([Message(role="user", content="hi")])

    assert result.usage.cost_usd is None


def test_messages_to_anthropic_round_trips_assistant_tool_calls() -> None:
    """Regression: a replayed assistant turn must emit tool_use blocks, and the
    tool result must map to a user tool_result referencing the tool_use id."""
    _, payload = _messages_to_anthropic(
        [
            Message(
                role="assistant",
                content="running tests",
                tool_calls=[ToolCall(id="toolu_1", name="run_tests", arguments={"path": "."})],
            ),
            Message(role="tool", content="ok", name="run_tests", tool_call_id="toolu_1"),
        ]
    )

    assistant = payload[0]
    assert assistant["role"] == "assistant"
    blocks = assistant["content"]
    assert blocks[0] == {"type": "text", "text": "running tests"}
    assert blocks[1] == {
        "type": "tool_use",
        "id": "toolu_1",
        "name": "run_tests",
        "input": {"path": "."},
    }

    tool_result = payload[1]
    assert tool_result["role"] == "user"
    assert tool_result["content"][0]["type"] == "tool_result"
    assert tool_result["content"][0]["tool_use_id"] == "toolu_1"


def test_raises_on_http_error() -> None:
    http = _FakeHttpClient(response=_FakeResponse(400, {}))
    provider = AnthropicProvider(model="claude-3-5-sonnet-20241022", api_key="sk-bad", http=http)

    with pytest.raises(ProviderRequestError):
        provider.complete([Message(role="user", content="hi")])
