"""Anthropic Messages API provider.

Different schema from the OpenAI-compatible providers:
- `system` is a top-level request field, not a message with role "system".
- `tools` use `input_schema` (not `parameters`) and no `type`/`function` wrapper.
- Tool calls come back as `content` blocks of type `tool_use`.
- Usage is `usage.input_tokens` / `usage.output_tokens`.

Cost: Anthropic's Messages API does not return a dollar cost, unlike
OpenRouter. This is the ONE place in the LLM layer where we need a
hand-maintained price table (input/output USD per million tokens). It is
injectable and defaults to empty; an unknown model yields `cost_usd=None`
rather than silently reporting a wrong number (MAJOR-3: never hand-roll a
number that looks provider-reported when it's actually our own guess).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from it2pr_worker.llm.base import LLMResponse, Message, ToolCall, ToolSpec, Usage

__all__ = [
    "AnthropicProvider",
    "ProviderRequestError",
    "HttpClient",
    "ModelPrice",
    "DEFAULT_PRICE_TABLE",
]

_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
_ANTHROPIC_VERSION = "2023-06-01"


class ProviderRequestError(RuntimeError):
    """Raised when the Anthropic HTTP call fails or returns an unexpected shape."""


class HttpClient(Protocol):
    def post(
        self, url: str, *, json: dict[str, Any], headers: dict[str, str]
    ) -> httpx.Response: ...


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """USD price per million tokens for a given model."""

    input_per_mtok: float
    output_per_mtok: float


# Deliberately empty by default: callers must opt in to a price table rather
# than getting a silently-maybe-stale hardcoded default (see module docstring).
DEFAULT_PRICE_TABLE: dict[str, ModelPrice] = {}


def _messages_to_anthropic(messages: list[Message]) -> tuple[str | None, list[dict[str, Any]]]:
    system: str | None = None
    system_parts: list[str] = []
    payload: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "system":
            system_parts.append(m.content)
            continue
        if m.role == "tool":
            payload.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": m.tool_call_id or "",
                            "content": m.content,
                        }
                    ],
                }
            )
            continue
        if m.role == "assistant" and m.tool_calls:
            blocks: list[dict[str, Any]] = []
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            blocks.extend(
                {
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.arguments,
                }
                for tc in m.tool_calls
            )
            payload.append({"role": "assistant", "content": blocks})
            continue
        payload.append({"role": m.role, "content": m.content})

    if system_parts:
        system = "\n".join(system_parts)
    return system, payload


def _tools_to_anthropic(tools: list[ToolSpec] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.parameters,
        }
        for t in tools
    ]


def _parse_content_blocks(blocks: list[dict[str, Any]]) -> tuple[str | None, list[ToolCall]]:
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in blocks:
        block_type = block.get("type")
        if block_type == "text":
            text_parts.append(block.get("text", ""))
        elif block_type == "tool_use":
            tool_calls.append(
                ToolCall(
                    id=block.get("id", ""),
                    name=block.get("name", ""),
                    arguments=block.get("input", {}) or {},
                )
            )
    content = "\n".join(text_parts) if text_parts else None
    return content, tool_calls


@dataclass(slots=True)
class AnthropicProvider:
    """Provider for the Anthropic Messages API."""

    model: str
    api_key: str
    http: HttpClient
    base_url: str = _DEFAULT_BASE_URL
    max_tokens: int = 4096
    price_table: dict[str, ModelPrice] = field(default_factory=dict)
    name: str = "anthropic"

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
    ) -> LLMResponse:
        system, anthropic_messages = _messages_to_anthropic(messages)

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": anthropic_messages,
        }
        if system is not None:
            payload["system"] = system

        anthropic_tools = _tools_to_anthropic(tools)
        if anthropic_tools is not None:
            payload["tools"] = anthropic_tools

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        response = self.http.post(
            f"{self.base_url}/messages", json=payload, headers=headers
        )
        if response.status_code >= 400:
            raise ProviderRequestError(
                f"Anthropic request failed: HTTP {response.status_code}"
            )

        body = response.json()
        try:
            blocks = body["content"]
        except KeyError as exc:
            raise ProviderRequestError("Anthropic response missing 'content'") from exc

        content, tool_calls = _parse_content_blocks(blocks)
        usage = self._parse_usage(body)

        return LLMResponse(content=content, tool_calls=tool_calls, usage=usage, raw=body)

    def _parse_usage(self, body: dict[str, Any]) -> Usage:
        usage_raw = body.get("usage") or {}
        prompt_tokens = int(usage_raw.get("input_tokens", 0) or 0)
        completion_tokens = int(usage_raw.get("output_tokens", 0) or 0)

        price = self.price_table.get(self.model)
        cost_usd: float | None = None
        if price is not None:
            cost_usd = (
                prompt_tokens / 1_000_000 * price.input_per_mtok
                + completion_tokens / 1_000_000 * price.output_per_mtok
            )

        return Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
        )
