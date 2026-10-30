"""Shared request/response mapping for OpenAI-compatible chat-completions schema.

Used by both `openrouter.py` and `openai_compatible.py`, which differ only in
base URL and how (or whether) they can recover a provider-reported cost.
"""

from __future__ import annotations

import json
from typing import Any

from it2pr_worker.llm.base import Message, ToolCall, ToolSpec


class ProviderRequestError(RuntimeError):
    """Raised when a provider HTTP call fails or returns an unexpected shape."""


def messages_to_openai(messages: list[Message]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for m in messages:
        entry: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.name is not None:
            entry["name"] = m.name
        if m.tool_call_id is not None:
            entry["tool_call_id"] = m.tool_call_id
        if m.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in m.tool_calls
            ]
        payload.append(entry)
    return payload


def tools_to_openai(tools: list[ToolSpec] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


def parse_tool_calls(raw_tool_calls: list[dict[str, Any]] | None) -> list[ToolCall]:
    if not raw_tool_calls:
        return []
    calls: list[ToolCall] = []
    for tc in raw_tool_calls:
        function = tc.get("function", {})
        arguments = _safe_json_loads(function.get("arguments", "{}"))
        calls.append(
            ToolCall(
                id=tc.get("id", ""),
                name=function.get("name", ""),
                arguments=arguments,
            )
        )
    return calls


def parse_message_choice(body: dict[str, Any]) -> dict[str, Any]:
    """Extract `choices[0].message`, raising `ProviderRequestError` if malformed."""
    try:
        return body["choices"][0]["message"]
    except (KeyError, IndexError) as exc:
        raise ProviderRequestError("Response missing expected 'choices[0].message'") from exc


def _safe_json_loads(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
