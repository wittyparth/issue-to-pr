"""OpenRouter provider — the default multiplexer (Axis C, C1).

Calls the OpenAI-compatible `POST /chat/completions` endpoint. Cost is the
PROVIDER-REPORTED value (MAJOR-3): OpenRouter can include a dollar cost in
the response's `usage` object when the request sets `usage: {"include":
true}`. If the response omits it, we fall back to `GET /generation?id=...`,
which also reports actual cost. We never compute cost from a token*price
guess.

`http` and `api_key` are injectable so tests never hit the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from it2pr_worker.llm._openai_schema import (
    ProviderRequestError,
    messages_to_openai,
    parse_message_choice,
    parse_tool_calls,
    tools_to_openai,
)
from it2pr_worker.llm.base import LLMResponse, Message, ToolSpec, Usage

__all__ = ["OpenRouterProvider", "ProviderRequestError", "HttpClient"]

_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


class HttpClient(Protocol):
    def post(
        self, url: str, *, json: dict[str, Any], headers: dict[str, str]
    ) -> httpx.Response: ...

    def get(
        self, url: str, *, params: dict[str, Any], headers: dict[str, str]
    ) -> httpx.Response: ...


@dataclass(slots=True)
class OpenRouterProvider:
    """Default multiplexer provider: OpenAI-compatible schema via OpenRouter."""

    model: str
    api_key: str
    http: HttpClient
    base_url: str = _DEFAULT_BASE_URL
    name: str = "openrouter"

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages_to_openai(messages),
            "usage": {"include": True},
        }
        openai_tools = tools_to_openai(tools)
        if openai_tools is not None:
            payload["tools"] = openai_tools

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        response = self.http.post(
            f"{self.base_url}/chat/completions", json=payload, headers=headers
        )
        if response.status_code >= 400:
            raise ProviderRequestError(
                f"OpenRouter request failed: HTTP {response.status_code}"
            )

        body = response.json()
        message = parse_message_choice(body)

        content = message.get("content")
        tool_calls = parse_tool_calls(message.get("tool_calls"))
        usage = self._parse_usage(body, headers=headers)

        return LLMResponse(content=content, tool_calls=tool_calls, usage=usage, raw=body)

    def _parse_usage(self, body: dict[str, Any], *, headers: dict[str, str]) -> Usage:
        usage_raw = body.get("usage") or {}
        prompt_tokens = int(usage_raw.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage_raw.get("completion_tokens", 0) or 0)
        cost_usd = usage_raw.get("cost")

        if cost_usd is None:
            generation_id = body.get("id")
            if generation_id:
                cost_usd = self._fetch_generation_cost(generation_id, headers=headers)

        return Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=float(cost_usd) if cost_usd is not None else None,
        )

    def _fetch_generation_cost(
        self, generation_id: str, *, headers: dict[str, str]
    ) -> float | None:
        response = self.http.get(
            f"{self.base_url}/generation",
            params={"id": generation_id},
            headers=headers,
        )
        if response.status_code >= 400:
            return None
        body = response.json()
        data = body.get("data") or {}
        cost = data.get("total_cost", data.get("cost"))
        return float(cost) if cost is not None else None
