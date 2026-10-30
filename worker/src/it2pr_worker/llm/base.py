"""Provider-agnostic LLM boundary.

The M4b agent loop depends ONLY on the types and `Provider` protocol defined
here — never on a concrete provider module (openrouter/openai_compatible/
anthropic). This keeps the loop swappable across providers (Principle 4:
provider/language agnosticism at the boundary).

Cost is always the PROVIDER-REPORTED usage/cost (MAJOR-3), never a hand-rolled
token tally: `Usage.cost_usd` is populated from the response payload where the
provider reports it, and left `None` where it doesn't (rather than guessing).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Message:
    """A single chat message. `role` is one of: system, user, assistant, tool.

    An assistant message that requested tool calls carries them in `tool_calls`
    so a replayed transcript includes the matching tool_use/tool_call the API
    requires before any tool-role result (otherwise the provider rejects the
    next turn with a 400).
    """

    role: str
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A tool definition offered to the model, JSON-schema `parameters`."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Usage:
    """Token/cost accounting for a single completion.

    `cost_usd` MUST come from the provider's own reported usage/cost field
    (or a documented, explicitly-configured price table for providers that
    don't report cost) — never a client-side token*price guess baked in
    silently. `None` means "unknown", not "zero".
    """

    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None = None


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Provider-agnostic result of a `complete()` call."""

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=lambda: Usage(prompt_tokens=0, completion_tokens=0))
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Provider(Protocol):
    """Narrow provider boundary. The agent loop (M4b) depends only on this."""

    name: str
    model: str

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
    ) -> LLMResponse: ...
