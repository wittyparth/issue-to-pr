from __future__ import annotations

from pathlib import Path

import pytest

from it2pr_worker.adapters.base import TestResult
from it2pr_worker.agent.limits import LimitTracker
from it2pr_worker.agent.loop import run_agent
from it2pr_worker.agent.tools import ToolContext
from it2pr_worker.llm.base import LLMResponse, Message, Provider, ToolCall, ToolSpec, Usage


class RecordingSpan:
    def __init__(self, tracer: RecordingTracer, name: str, meta: dict) -> None:
        self._tracer = tracer
        self.name = name
        self.start_meta = meta
        self.end_meta: dict | None = None

    def end(self, **meta: object) -> None:
        self.end_meta = meta
        self._tracer.ended_spans.append(self)

    def __enter__(self) -> RecordingSpan:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.end()


class RecordingTrace:
    def __init__(self, tracer: RecordingTracer, name: str, meta: dict) -> None:
        self._tracer = tracer
        self.name = name
        self.meta = meta
        self.id = "trace-1"
        self.ended = False
        self.end_meta: dict | None = None

    def span(self, name: str, **meta: object) -> RecordingSpan:
        span = RecordingSpan(self._tracer, name, meta)
        self._tracer.spans.append(span)
        return span

    def end(self, **meta: object) -> None:
        self.ended = True
        self.end_meta = meta

    @property
    def trace_url(self) -> str:
        return f"https://example.com/trace/{self.id}"


class RecordingTracer:
    """Fake `Tracer` that records every trace/span opened during a run."""

    def __init__(self) -> None:
        self.traces: list[RecordingTrace] = []
        self.spans: list[RecordingSpan] = []
        self.ended_spans: list[RecordingSpan] = []

    def trace(self, name: str, **meta: object) -> RecordingTrace:
        trace = RecordingTrace(self, name, meta)
        self.traces.append(trace)
        return trace


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


class ScriptedProvider:
    """Fake `Provider` returning pre-scripted responses, one per turn."""

    name = "fake"
    model = "fake-model"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = responses
        self.calls: list[list[Message]] = []

    def complete(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> LLMResponse:
        self.calls.append(list(messages))
        idx = min(len(self.calls) - 1, len(self._responses) - 1)
        return self._responses[idx]


class LoopingProvider:
    """Fake `Provider` that always returns the same tool call (never finishes)."""

    name = "fake"
    model = "fake-model"

    def __init__(self, response: LLMResponse) -> None:
        self._response = response
        self.count = 0

    def complete(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> LLMResponse:
        self.count += 1
        return self._response


class FakeAdapter:
    name = "fake"

    def __init__(self, passed: bool = True) -> None:
        self._passed = passed

    def detect(self, repo_dir: Path) -> bool:
        return True

    def install(self, repo_dir: Path, *, runner: object = None) -> None:
        return None

    def test_command(self, repo_dir: Path) -> list[str]:
        return ["pytest"]

    def run_tests(self, repo_dir: Path, *, runner: object = None) -> TestResult:
        return TestResult(passed=self._passed, output_tail="ok")

    def coverage(self, repo_dir: Path, *, runner: object = None) -> float | None:
        return 90.0


def _tc(name: str, cid: str = "c1", **args: object) -> ToolCall:
    return ToolCall(id=cid, name=name, arguments=dict(args))


def _resp(tool_calls: list[ToolCall], cost: float | None = 0.0) -> LLMResponse:
    return LLMResponse(
        content=None,
        tool_calls=tool_calls,
        usage=Usage(prompt_tokens=1, completion_tokens=1, cost_usd=cost),
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    (r / "bug.py").write_text("def add(a, b):\n    return a - b\n")
    (r / ".github" / "workflows").mkdir(parents=True)
    (r / ".github" / "workflows" / "deploy.yml").write_text("on: push\n")
    return r


def test_loop_depends_only_on_provider_protocol() -> None:
    # The scripted fake satisfies the Provider protocol structurally.
    provider = ScriptedProvider([_resp([_tc("finish", summary="x")])])
    assert isinstance(provider, Provider)


def test_scripted_fix_finishes(repo: Path) -> None:
    clock = FakeClock()
    provider = ScriptedProvider(
        [
            _resp(
                [_tc("edit_file", "e1", path="bug.py", old_str="a - b", new_str="a + b")],
                cost=0.5,
            ),
            _resp([_tc("run_tests", "t1")], cost=0.5),
            _resp([_tc("finish", "f1", summary="fixed the bug")], cost=0.5),
        ]
    )
    ctx = ToolContext(repo_dir=repo, adapter=FakeAdapter(passed=True))
    limits = LimitTracker(clock=clock)

    result = run_agent(
        provider,
        ctx,
        issue_title="add is wrong",
        issue_body="add subtracts",
        limits=limits,
    )

    assert result.status == "finished"
    assert result.turns == 3
    assert result.summary == "fixed the bug"
    assert result.cost_usd == pytest.approx(1.5)
    # The edit was actually applied.
    assert (repo / "bug.py").read_text() == "def add(a, b):\n    return a + b\n"


def test_limit_turns(repo: Path) -> None:
    clock = FakeClock()
    provider = LoopingProvider(_resp([_tc("repo_map", "m1")], cost=0.0))
    ctx = ToolContext(repo_dir=repo)
    limits = LimitTracker(max_turns=5, clock=clock)

    result = run_agent(
        provider, ctx, issue_title="t", issue_body="b", limits=limits
    )

    assert result.status == "limit_turns"
    assert result.turns == 5
    assert provider.count == 5


def test_limit_cost(repo: Path) -> None:
    clock = FakeClock()
    provider = LoopingProvider(_resp([_tc("repo_map", "m1")], cost=10.0))
    ctx = ToolContext(repo_dir=repo)
    limits = LimitTracker(max_turns=100, max_cost_usd=25.0, clock=clock)

    result = run_agent(
        provider, ctx, issue_title="t", issue_body="b", limits=limits
    )

    assert result.status == "limit_cost"
    # 3 turns * 10 = 30 >= 25
    assert result.turns == 3
    assert result.cost_usd == pytest.approx(30.0)


def test_limit_time(repo: Path) -> None:
    clock = FakeClock()

    class TimeJumpProvider:
        name = "fake"
        model = "fake-model"

        def __init__(self) -> None:
            self.count = 0

        def complete(
            self, messages: list[Message], tools: list[ToolSpec] | None = None
        ) -> LLMResponse:
            self.count += 1
            clock.advance(700.0)  # each turn burns 700s
            return _resp([_tc("repo_map", "m1")], cost=0.0)

    provider = TimeJumpProvider()
    ctx = ToolContext(repo_dir=repo)
    limits = LimitTracker(max_turns=100, wall_clock_seconds=1800.0, clock=clock)

    result = run_agent(
        provider, ctx, issue_title="t", issue_body="b", limits=limits
    )

    assert result.status == "limit_time"
    # 700*3 = 2100 >= 1800
    assert result.turns == 3


def test_allowlist_during_loop_blocks_workflow_edit_and_continues(repo: Path) -> None:
    clock = FakeClock()
    original = (repo / ".github" / "workflows" / "deploy.yml").read_text()
    provider = ScriptedProvider(
        [
            _resp([_tc("edit_file", "e1", path=".github/workflows/deploy.yml",
                       old_str="push", new_str="hacked")], cost=0.1),
            _resp([_tc("finish", "f1", summary="done")], cost=0.1),
        ]
    )
    ctx = ToolContext(repo_dir=repo, adapter=FakeAdapter())
    limits = LimitTracker(clock=clock)

    result = run_agent(
        provider, ctx, issue_title="t", issue_body="b", limits=limits
    )

    # File untouched, loop continued to finish.
    assert (repo / ".github" / "workflows" / "deploy.yml").read_text() == original
    assert result.status == "finished"
    assert result.turns == 2
    # The blocked edit produced a visible tool error message.
    tool_msgs = [m for m in result.messages if m.role == "tool" and m.name == "edit_file"]
    assert tool_msgs
    assert "workflows" in tool_msgs[0].content


def test_default_noop_tracer_behaves_exactly_as_before(repo: Path) -> None:
    """No `tracer` kwarg passed: behavior must be identical to pre-M7 tests."""
    clock = FakeClock()
    provider = ScriptedProvider(
        [
            _resp([_tc("run_tests", "t1")], cost=0.5),
            _resp([_tc("finish", "f1", summary="fixed the bug")], cost=0.5),
        ]
    )
    ctx = ToolContext(repo_dir=repo, adapter=FakeAdapter(passed=True))
    limits = LimitTracker(clock=clock)

    result = run_agent(
        provider, ctx, issue_title="t", issue_body="b", limits=limits
    )

    assert result.status == "finished"
    assert result.turns == 2
    assert result.summary == "fixed the bug"


def test_injected_tracer_opens_trace_and_one_span_per_turn(repo: Path) -> None:
    clock = FakeClock()
    provider = ScriptedProvider(
        [
            _resp([_tc("run_tests", "t1")], cost=0.5),
            _resp([_tc("repo_map", "t2")], cost=0.1),
            _resp([_tc("finish", "f1", summary="fixed the bug")], cost=0.2),
        ]
    )
    ctx = ToolContext(repo_dir=repo, adapter=FakeAdapter(passed=True))
    limits = LimitTracker(clock=clock)
    tracer = RecordingTracer()

    result = run_agent(
        provider,
        ctx,
        issue_title="t",
        issue_body="b",
        limits=limits,
        tracer=tracer,
    )

    assert result.status == "finished"
    assert len(tracer.traces) == 1
    trace = tracer.traces[0]
    assert trace.ended is True

    # One span per turn (3 turns).
    assert len(tracer.spans) == 3
    assert [span.start_meta["turn"] for span in tracer.spans] == [1, 2, 3]
    assert tracer.spans[0].start_meta["tool_names"] == ["run_tests"]
    assert tracer.spans[1].start_meta["tool_names"] == ["repo_map"]
    assert tracer.spans[2].start_meta["tool_names"] == ["finish"]
    # Every span was ended.
    assert len(tracer.ended_spans) == 3


def test_replayed_assistant_turn_carries_tool_calls_before_tool_result(repo: Path) -> None:
    """Regression: on turn 2 the transcript must contain an assistant message
    with tool_calls immediately before the tool result, or the real API 400s."""
    clock = FakeClock()

    class AssertingProvider:
        name = "fake"
        model = "fake-model"

        def __init__(self, responses: list[LLMResponse]) -> None:
            self._responses = responses
            self.calls = 0

        def complete(
            self, messages: list[Message], tools: list[ToolSpec] | None = None
        ) -> LLMResponse:
            if self.calls == 1:
                # Turn 2: locate the tool result and assert the message right
                # before it is an assistant message carrying the matching call.
                tool_idx = next(i for i, m in enumerate(messages) if m.role == "tool")
                prior = messages[tool_idx - 1]
                assert prior.role == "assistant"
                assert prior.tool_calls, "assistant turn dropped tool_calls"
                assert prior.tool_calls[0].id == messages[tool_idx].tool_call_id
            resp = self._responses[self.calls]
            self.calls += 1
            return resp

    provider = AssertingProvider(
        [
            _resp([_tc("run_tests", "t1")], cost=0.1),
            _resp([_tc("finish", "f1", summary="done")], cost=0.1),
        ]
    )
    ctx = ToolContext(repo_dir=repo, adapter=FakeAdapter(passed=True))
    limits = LimitTracker(clock=clock)

    result = run_agent(provider, ctx, issue_title="t", issue_body="b", limits=limits)

    assert result.status == "finished"
    assert provider.calls == 2


def test_injected_tracer_records_limit_status_on_end(repo: Path) -> None:
    clock = FakeClock()
    provider = LoopingProvider(_resp([_tc("repo_map", "m1")], cost=0.0))
    ctx = ToolContext(repo_dir=repo)
    limits = LimitTracker(max_turns=2, clock=clock)
    tracer = RecordingTracer()

    result = run_agent(
        provider, ctx, issue_title="t", issue_body="b", limits=limits, tracer=tracer
    )

    assert result.status == "limit_turns"
    assert len(tracer.traces) == 1
    assert tracer.traces[0].ended is True
    assert tracer.traces[0].end_meta["status"] == "turns"
    assert len(tracer.spans) == 2
