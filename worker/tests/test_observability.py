from __future__ import annotations

from typing import Any

import pytest

from it2pr_worker.observability import (
    LangfuseTracer,
    NoOpTracer,
    build_tracer,
)


class FakeResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code


class RecordingHttp:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, *, json: Any, headers: Any, auth: Any = None) -> FakeResponse:
        self.calls.append({"url": url, "json": json, "headers": headers, "auth": auth})
        return FakeResponse()


class RaisingHttp:
    def post(self, url: str, *, json: Any, headers: Any, auth: Any = None) -> FakeResponse:
        raise ConnectionError("langfuse unreachable")


def test_noop_tracer_records_nothing() -> None:
    tracer = NoOpTracer()
    trace = tracer.trace("run")
    span = trace.span("turn", turn=1)
    span.end(cost_usd=0.1)
    trace.end(status="finished")
    assert trace.trace_url == ""


def test_noop_tracer_span_context_manager() -> None:
    tracer = NoOpTracer()
    trace = tracer.trace("run")
    with trace.span("turn") as span:
        assert span is not None


def test_langfuse_tracer_posts_via_injected_http() -> None:
    http = RecordingHttp()
    tracer = LangfuseTracer("pub", "secret", "https://cloud.langfuse.com", http=http)

    trace = tracer.trace("agent-run", issue_title="fix bug")
    span = trace.span("turn", turn=1, tool_names=["read_file"])
    span.end(cost_usd=0.25)
    trace.end(status="finished")

    assert len(http.calls) == 4  # trace-create, span-create, span-update, trace-create(end)
    for call in http.calls:
        assert call["url"] == "https://cloud.langfuse.com/api/public/ingestion"
        assert call["auth"] == ("pub", "secret")


def test_langfuse_tracer_swallows_http_error() -> None:
    tracer = LangfuseTracer("pub", "secret", "https://cloud.langfuse.com", http=RaisingHttp())

    # None of these should raise, even though the injected http always raises.
    trace = tracer.trace("agent-run")
    span = trace.span("turn")
    span.end()
    trace.end()


def test_trace_url_format() -> None:
    tracer = LangfuseTracer("pub", "secret", "https://cloud.langfuse.com/", http=RecordingHttp())
    trace = tracer.trace("agent-run")
    assert trace.trace_url == f"https://cloud.langfuse.com/trace/{trace.id}"


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"LANGFUSE_PUBLIC_KEY": "pub"},
        {"LANGFUSE_PUBLIC_KEY": "pub", "LANGFUSE_SECRET_KEY": "secret"},
    ],
)
def test_build_tracer_returns_noop_without_full_env(env: dict[str, str]) -> None:
    tracer = build_tracer(env=env)
    assert isinstance(tracer, NoOpTracer)


def test_build_tracer_returns_langfuse_tracer_with_full_env() -> None:
    env = {
        "LANGFUSE_PUBLIC_KEY": "pub",
        "LANGFUSE_SECRET_KEY": "secret",
        "LANGFUSE_HOST": "https://cloud.langfuse.com",
    }
    tracer = build_tracer(env=env, http=RecordingHttp())
    assert isinstance(tracer, LangfuseTracer)
