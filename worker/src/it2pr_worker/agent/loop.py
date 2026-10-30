"""The provider-agnostic agent loop (M4, D1 mini-swe-agent-style).

`run_agent` drives a fix loop entirely through the injected `Provider` abstraction
(never a concrete provider) and an injected `clock` (via `LimitTracker`), so it is
deterministic and fully testable with a scripted fake provider.

Each turn: call `provider.complete(messages, tools)`, append the assistant message,
feed `usage.cost_usd` to the limit tracker, execute any tool calls via `dispatch`
(the allow-list is enforced there), append tool results, and stop when the model
calls `finish` or a hard limit is exceeded. Hitting a limit is terminal — the loop
does NOT open a PR or push anything; that is M5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from it2pr_worker.llm.base import Message, Provider
from it2pr_worker.observability import NoOpTracer, Tracer

from .limits import LimitKind, LimitTracker
from .tools import FINISH_TOOL, ToolContext, build_toolset, dispatch, repo_map

AgentStatus = Literal["finished", "limit_turns", "limit_time", "limit_cost", "error"]

_DEFAULT_SYSTEM_PROMPT = (
    "You are an autonomous software engineer fixing a GitHub issue in a cloned "
    "repository. Use the provided tools to explore the code, make the smallest "
    "correct change, and run the tests. When the issue is resolved and tests "
    "pass, call the `finish` tool with a short rationale. Never edit CI "
    "configuration under .github/workflows/."
)

_LIMIT_TO_STATUS: dict[LimitKind, AgentStatus] = {
    LimitKind.TURNS: "limit_turns",
    LimitKind.TIME: "limit_time",
    LimitKind.COST: "limit_cost",
}


@dataclass(frozen=True, slots=True)
class AgentResult:
    status: AgentStatus
    turns: int
    cost_usd: float | None
    summary: str
    messages: list[Message] = field(default_factory=list)


def _initial_messages(
    system_prompt: str, issue_title: str, issue_body: str, repo_overview: str
) -> list[Message]:
    user = (
        f"# Issue: {issue_title}\n\n"
        f"{issue_body}\n\n"
        f"## Repository files\n{repo_overview}\n"
    )
    return [
        Message(role="system", content=system_prompt),
        Message(role="user", content=user),
    ]


def run_agent(
    provider: Provider,
    ctx: ToolContext,
    *,
    issue_title: str,
    issue_body: str,
    limits: LimitTracker,
    system_prompt: str | None = None,
    tracer: Tracer | None = None,
) -> AgentResult:
    """Run the fix loop until the model finishes or a hard limit is exceeded.

    Depends only on the `Provider` abstraction and the injected `clock` (through
    `limits`), so a scripted fake provider + fake clock make it fully hermetic.
    `tracer` is optional and defaults to a no-op so existing callers/tests are
    unaffected; when a real tracer is injected, one trace is opened for the run
    and one span per turn (recording turn index, tool names, and cost).
    """
    tools = build_toolset()
    repo_overview = repo_map(ctx).content
    messages = _initial_messages(
        system_prompt or _DEFAULT_SYSTEM_PROMPT,
        issue_title,
        issue_body,
        repo_overview,
    )

    limits.start()
    trace = (tracer or NoOpTracer()).trace("agent-run", issue_title=issue_title)

    while True:
        turn_index = limits.turns + 1
        response = provider.complete(messages, tools)
        limits.record_turn()
        limits.add_cost(response.usage.cost_usd)

        messages.append(
            Message(
                role="assistant",
                content=response.content or "",
                tool_calls=list(response.tool_calls),
            )
        )

        tool_names = [call.name for call in response.tool_calls]
        span = trace.span(
            "turn",
            turn=turn_index,
            tool_names=tool_names,
            cost_usd=response.usage.cost_usd,
        )

        finished_summary: str | None = None
        for call in response.tool_calls:
            if call.name == FINISH_TOOL:
                finished_summary = call.arguments.get("summary", "") if call.arguments else ""
                messages.append(
                    Message(
                        role="tool",
                        content=finished_summary,
                        name=FINISH_TOOL,
                        tool_call_id=call.id,
                    )
                )
                break
            result = dispatch(call, ctx)
            messages.append(
                Message(
                    role="tool",
                    content=result.content,
                    name=call.name,
                    tool_call_id=call.id,
                )
            )

        span.end()

        if finished_summary is not None:
            trace.end(status="finished", turns=limits.turns)
            return AgentResult(
                status="finished",
                turns=limits.turns,
                cost_usd=limits.cost_usd,
                summary=finished_summary,
                messages=messages,
            )

        status = limits.check()
        if status.exceeded:
            trace.end(status=str(status.kind), turns=limits.turns)
            return AgentResult(
                status=_LIMIT_TO_STATUS[status.kind],
                turns=limits.turns,
                cost_usd=limits.cost_usd,
                summary=status.detail,
                messages=messages,
            )
