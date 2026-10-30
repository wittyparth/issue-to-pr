from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from it2pr_worker.llm.base import Message, ToolSpec
from it2pr_worker.llm.openrouter import OpenRouterProvider, ProviderRequestError


@dataclass
class _FakeResponse:
    status_code: int
    _body: dict[str, Any]

    def json(self) -> dict[str, Any]:
        return self._body


@dataclass
class _FakeHttpClient:
    post_responses: list[_FakeResponse]
    get_responses: list[_FakeResponse] = field(default_factory=list)
    post_calls: list[tuple[str, dict[str, Any], dict[str, str]]] = field(default_factory=list)
    get_calls: list[tuple[str, dict[str, Any], dict[str, str]]] = field(default_factory=list)

    def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        self.post_calls.append((url, json, headers))
        return self.post_responses[len(self.post_calls) - 1]

    def get(self, url: str, *, params: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        self.get_calls.append((url, params, headers))
        return self.get_responses[len(self.get_calls) - 1]


def _completion_body(
    *,
    content: str | None = "Here is the fix.",
    tool_calls: list[dict[str, Any]] | None = None,
    usage: dict[str, Any] | None = None,
    generation_id: str | None = "gen-123",
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    body: dict[str, Any] = {"choices": [{"message": message}]}
    if generation_id is not None:
        body["id"] = generation_id
    if usage is not None:
        body["usage"] = usage
    return body


def test_complete_parses_content_and_reported_cost() -> None:
    body = _completion_body(
        usage={"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.0042},
    )
    http = _FakeHttpClient(post_responses=[_FakeResponse(200, body)])
    provider = OpenRouterProvider(model="anthropic/claude-3.5-sonnet", api_key="sk-or-x", http=http)

    result = provider.complete([Message(role="user", content="fix the bug")])

    assert result.content == "Here is the fix."
    assert result.tool_calls == []
    # Cost must be read directly from the fixture's reported value, not derived.
    assert result.usage.cost_usd == pytest.approx(0.0042, abs=1e-9)
    assert result.usage.prompt_tokens == 100
    assert result.usage.completion_tokens == 50
    assert len(http.get_calls) == 0  # generation endpoint not needed


def test_complete_parses_tool_calls() -> None:
    body = _completion_body(
        content=None,
        tool_calls=[
            {
                "id": "call_1",
                "function": {"name": "run_tests", "arguments": '{"path": "."}'},
            }
        ],
        usage={"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0001},
    )
    http = _FakeHttpClient(post_responses=[_FakeResponse(200, body)])
    provider = OpenRouterProvider(model="anthropic/claude-3.5-sonnet", api_key="sk-or-x", http=http)

    result = provider.complete(
        [Message(role="user", content="run tests")],
        tools=[ToolSpec(name="run_tests", description="run tests", parameters={})],
    )

    assert result.content is None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "run_tests"
    assert result.tool_calls[0].arguments == {"path": "."}

    # Request mapped our ToolSpec into OpenAI-style tools.
    _, sent_json, _ = http.post_calls[0]
    assert sent_json["tools"][0]["function"]["name"] == "run_tests"


def test_cost_fetched_from_generation_endpoint_when_missing_from_response() -> None:
    body = _completion_body(usage={"prompt_tokens": 20, "completion_tokens": 10})
    generation_body = {"data": {"id": "gen-123", "total_cost": 0.0007}}
    http = _FakeHttpClient(
        post_responses=[_FakeResponse(200, body)],
        get_responses=[_FakeResponse(200, generation_body)],
    )
    provider = OpenRouterProvider(model="anthropic/claude-3.5-sonnet", api_key="sk-or-x", http=http)

    result = provider.complete([Message(role="user", content="fix the bug")])

    assert result.usage.cost_usd == pytest.approx(0.0007, abs=1e-9)
    assert len(http.get_calls) == 1
    url, params, _ = http.get_calls[0]
    assert url.endswith("/generation")
    assert params["id"] == "gen-123"


def test_cost_none_when_unavailable_from_either_source() -> None:
    body = _completion_body(usage={"prompt_tokens": 20, "completion_tokens": 10})
    generation_body = {"data": {}}
    http = _FakeHttpClient(
        post_responses=[_FakeResponse(200, body)],
        get_responses=[_FakeResponse(200, generation_body)],
    )
    provider = OpenRouterProvider(model="anthropic/claude-3.5-sonnet", api_key="sk-or-x", http=http)

    result = provider.complete([Message(role="user", content="fix the bug")])

    assert result.usage.cost_usd is None


def test_complete_raises_on_http_error() -> None:
    http = _FakeHttpClient(post_responses=[_FakeResponse(500, {})])
    provider = OpenRouterProvider(model="anthropic/claude-3.5-sonnet", api_key="sk-or-x", http=http)

    with pytest.raises(ProviderRequestError):
        provider.complete([Message(role="user", content="fix the bug")])


def test_complete_sends_bearer_auth_header() -> None:
    body = _completion_body(usage={"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.0})
    http = _FakeHttpClient(post_responses=[_FakeResponse(200, body)])
    provider = OpenRouterProvider(
        model="anthropic/claude-3.5-sonnet", api_key="sk-or-secret", http=http
    )

    provider.complete([Message(role="user", content="hi")])

    _, _, headers = http.post_calls[0]
    assert headers["Authorization"] == "Bearer sk-or-secret"
