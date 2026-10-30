from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from it2pr_worker.llm._openai_schema import messages_to_openai
from it2pr_worker.llm.base import Message, ToolCall, ToolSpec
from it2pr_worker.llm.openai_compatible import OpenAICompatibleProvider, ProviderRequestError


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


def test_request_uses_base_url_model_and_auth_header() -> None:
    body = {
        "choices": [{"message": {"role": "assistant", "content": "done"}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3},
    }
    http = _FakeHttpClient(response=_FakeResponse(200, body))
    provider = OpenAICompatibleProvider(
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
        api_key="sk-deepseek-x",
        http=http,
    )

    provider.complete([Message(role="user", content="hello")])

    url, sent_json, headers = http.calls[0]
    assert url == "https://api.deepseek.com/v1/chat/completions"
    assert sent_json["model"] == "deepseek-chat"
    assert headers["Authorization"] == "Bearer sk-deepseek-x"


def test_response_parsed_into_llm_response() -> None:
    body = {
        "choices": [{"message": {"role": "assistant", "content": "the answer"}}],
        "usage": {"prompt_tokens": 42, "completion_tokens": 7},
    }
    http = _FakeHttpClient(response=_FakeResponse(200, body))
    provider = OpenAICompatibleProvider(
        base_url="https://api.openai.com/v1", model="gpt-4o", api_key="sk-x", http=http
    )

    result = provider.complete([Message(role="user", content="hi")])

    assert result.content == "the answer"
    assert result.usage.prompt_tokens == 42
    assert result.usage.completion_tokens == 7


def test_cost_none_when_endpoint_omits_it() -> None:
    body = {
        "choices": [{"message": {"role": "assistant", "content": "the answer"}}],
        "usage": {"prompt_tokens": 42, "completion_tokens": 7},
    }
    http = _FakeHttpClient(response=_FakeResponse(200, body))
    provider = OpenAICompatibleProvider(
        base_url="https://api.deepseek.com/v1", model="deepseek-chat", api_key="sk-x", http=http
    )

    result = provider.complete([Message(role="user", content="hi")])

    assert result.usage.cost_usd is None


def test_cost_populated_when_endpoint_reports_it() -> None:
    body = {
        "choices": [{"message": {"role": "assistant", "content": "the answer"}}],
        "usage": {"prompt_tokens": 42, "completion_tokens": 7, "cost": 0.0015},
    }
    http = _FakeHttpClient(response=_FakeResponse(200, body))
    provider = OpenAICompatibleProvider(
        base_url="https://api.openai.com/v1", model="gpt-4o", api_key="sk-x", http=http
    )

    result = provider.complete([Message(role="user", content="hi")])

    assert result.usage.cost_usd == pytest.approx(0.0015, abs=1e-9)


def test_tools_mapped_to_openai_schema() -> None:
    body = {"choices": [{"message": {"role": "assistant", "content": None}}], "usage": {}}
    http = _FakeHttpClient(response=_FakeResponse(200, body))
    provider = OpenAICompatibleProvider(
        base_url="https://api.openai.com/v1", model="gpt-4o", api_key="sk-x", http=http
    )

    provider.complete(
        [Message(role="user", content="run")],
        tools=[ToolSpec(name="edit_file", description="edit", parameters={"type": "object"})],
    )

    _, sent_json, _ = http.calls[0]
    assert sent_json["tools"][0]["function"]["name"] == "edit_file"
    assert sent_json["tools"][0]["function"]["parameters"] == {"type": "object"}


def test_raises_on_http_error() -> None:
    http = _FakeHttpClient(response=_FakeResponse(401, {}))
    provider = OpenAICompatibleProvider(
        base_url="https://api.openai.com/v1", model="gpt-4o", api_key="sk-bad", http=http
    )

    with pytest.raises(ProviderRequestError):
        provider.complete([Message(role="user", content="hi")])


def test_messages_to_openai_round_trips_assistant_tool_calls() -> None:
    """Regression: a replayed assistant turn must emit its tool_calls, and the
    following tool result must carry the matching tool_call_id."""
    messages = [
        Message(
            role="assistant",
            content="running tests",
            tool_calls=[ToolCall(id="c1", name="run_tests", arguments={"path": "."})],
        ),
        Message(role="tool", content="ok", name="run_tests", tool_call_id="c1"),
    ]

    payload = messages_to_openai(messages)

    assistant = payload[0]
    assert assistant["role"] == "assistant"
    assert assistant["tool_calls"][0]["id"] == "c1"
    assert assistant["tool_calls"][0]["type"] == "function"
    assert assistant["tool_calls"][0]["function"]["name"] == "run_tests"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"path": "."}

    tool_msg = payload[1]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "c1"
