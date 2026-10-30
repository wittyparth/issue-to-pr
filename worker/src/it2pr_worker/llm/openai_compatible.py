"""Generic OpenAI-compatible provider (OpenAI itself, DeepSeek, local endpoints).

Same request/response mapping as OpenRouter (OpenAI chat-completions schema)
but against an arbitrary `base_url`. Cost is populated from the response
`usage` object ONLY if the endpoint reports it (some OpenAI-compatible
endpoints, e.g. DeepSeek, may not); otherwise `Usage.cost_usd` is `None`.
We deliberately do not hand-roll a token*price fallback here (MAJOR-3):
generic endpoints vary too much in pricing to guess reliably.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from it2pr_worker.llm._openai_schema import (
    ProviderRequestError,
    messages_to_openai,
    parse_message_choice,
    parse_tool_calls,
    tools_to_openai,
)
from it2pr_worker.llm.base import LLMResponse, Message, ToolSpec, Usage
from it2pr_worker.llm.openrouter import HttpClient

__all__ = ["OpenAICompatibleProvider", "ProviderRequestError"]


@dataclass(slots=True)
class OpenAICompatibleProvider:
    """Provider for any OpenAI-compatible chat-completions endpoint."""

    base_url: str
    model: str
    api_key: str
    http: HttpClient
    name: str = "openai-compatible"

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages_to_openai(messages),
        }
        openai_tools = tools_to_openai(tools)
        if openai_tools is not None:
            payload["tools"] = openai_tools

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        response = self.http.post(url, json=payload, headers=headers)
        if response.status_code >= 400:
            raise ProviderRequestError(
                f"OpenAI-compatible request failed: HTTP {response.status_code}"
            )

        body = response.json()
        message = parse_message_choice(body)

        content = message.get("content")
        tool_calls = parse_tool_calls(message.get("tool_calls"))

        usage_raw = body.get("usage") or {}
        prompt_tokens = int(usage_raw.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage_raw.get("completion_tokens", 0) or 0)
        cost_usd = usage_raw.get("cost")

        usage = Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=float(cost_usd) if cost_usd is not None else None,
        )

        return LLMResponse(content=content, tool_calls=tool_calls, usage=usage, raw=body)
