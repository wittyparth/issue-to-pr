"""Injectable tracing boundary (M7, Axis E — Langfuse managed free tier).

The agent loop and post-result step depend only on the `Tracer`/`Trace`
protocols defined here, never on the Langfuse SDK directly — we talk to
Langfuse's HTTP ingestion API via injectable `httpx` instead of adding the
heavy `langfuse` package as a dependency.

`NoOpTracer` is the default everywhere so existing code and tests are
unaffected unless a real tracer is explicitly wired in. `LangfuseTracer`
swallows any transport failure: observability must never break a run.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

import httpx

_INGESTION_PATH = "/api/public/ingestion"


@runtime_checkable
class Span(Protocol):
    """A single span within a trace; supports use as a context manager."""

    def end(self, **meta: Any) -> None: ...  # noqa: ANN401

    def __enter__(self) -> Span: ...

    def __exit__(self, *exc_info: object) -> None: ...


@runtime_checkable
class Trace(Protocol):
    """A single run's trace; opens spans and exposes the trace URL."""

    id: str

    def span(self, name: str, **meta: Any) -> Span: ...  # noqa: ANN401

    def end(self, **meta: Any) -> None: ...  # noqa: ANN401

    @property
    def trace_url(self) -> str: ...


@runtime_checkable
class Tracer(Protocol):
    """Top-level tracer boundary. The agent loop depends only on this."""

    def trace(self, name: str, **meta: Any) -> Trace: ...  # noqa: ANN401


# --- no-op implementation ---------------------------------------------------


class _NoOpSpan:
    def end(self, **meta: Any) -> None:  # noqa: ANN401
        return None

    def __enter__(self) -> _NoOpSpan:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


class _NoOpTrace:
    def __init__(self) -> None:
        self.id = ""

    def span(self, name: str, **meta: Any) -> _NoOpSpan:  # noqa: ANN401
        return _NoOpSpan()

    def end(self, **meta: Any) -> None:  # noqa: ANN401
        return None

    @property
    def trace_url(self) -> str:
        return ""


class NoOpTracer:
    """Records nothing. Safe default so untraced code paths are unaffected."""

    def trace(self, name: str, **meta: Any) -> _NoOpTrace:  # noqa: ANN401
        return _NoOpTrace()


# --- Langfuse HTTP-ingestion implementation ---------------------------------


class HttpPost(Protocol):
    def post(
        self, url: str, *, json: Any, headers: Mapping[str, str], auth: Any = None  # noqa: ANN401
    ) -> httpx.Response: ...


def _new_id() -> str:
    return uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class LangfuseSpan:
    _tracer: LangfuseTracer
    trace_id: str
    id: str = field(default_factory=_new_id)
    name: str = ""

    def end(self, **meta: Any) -> None:  # noqa: ANN401
        self._tracer._send_span_end(self, meta)

    def __enter__(self) -> LangfuseSpan:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.end()


@dataclass(slots=True)
class LangfuseTrace:
    _tracer: LangfuseTracer
    id: str
    name: str = ""

    def span(self, name: str, **meta: Any) -> LangfuseSpan:  # noqa: ANN401
        span = LangfuseSpan(_tracer=self._tracer, trace_id=self.id, name=name)
        self._tracer._send_span_start(span, name, meta)
        return span

    def end(self, **meta: Any) -> None:  # noqa: ANN401
        self._tracer._send_trace_end(self, meta)

    @property
    def trace_url(self) -> str:
        return self._tracer.trace_url(self.id)


class LangfuseTracer:
    """Posts trace/span events to Langfuse's ingestion endpoint via `httpx`.

    All transport failures are swallowed (caught and ignored) — a tracing
    outage must never break the worker run.
    """

    def __init__(
        self,
        public_key: str,
        secret_key: str,
        host: str,
        *,
        http: HttpPost | None = None,
    ) -> None:
        self._public_key = public_key
        self._secret_key = secret_key
        self._host = host.rstrip("/")
        self._http = http if http is not None else httpx.Client()

    def trace_url(self, trace_id: str) -> str:
        return f"{self._host}/trace/{trace_id}"

    def trace(self, name: str, **meta: Any) -> LangfuseTrace:  # noqa: ANN401
        trace_id = _new_id()
        trace = LangfuseTrace(_tracer=self, id=trace_id, name=name)
        self._safe_ingest(
            [
                {
                    "id": _new_id(),
                    "type": "trace-create",
                    "timestamp": _now_iso(),
                    "body": {"id": trace_id, "name": name, "metadata": meta},
                }
            ]
        )
        return trace

    def _send_span_start(self, span: LangfuseSpan, name: str, meta: dict[str, Any]) -> None:
        self._safe_ingest(
            [
                {
                    "id": _new_id(),
                    "type": "span-create",
                    "timestamp": _now_iso(),
                    "body": {
                        "id": span.id,
                        "traceId": span.trace_id,
                        "name": name,
                        "metadata": meta,
                    },
                }
            ]
        )

    def _send_span_end(self, span: LangfuseSpan, meta: dict[str, Any]) -> None:
        self._safe_ingest(
            [
                {
                    "id": _new_id(),
                    "type": "span-update",
                    "timestamp": _now_iso(),
                    "body": {
                        "id": span.id,
                        "traceId": span.trace_id,
                        "metadata": meta,
                        "endTime": _now_iso(),
                    },
                }
            ]
        )

    def _send_trace_end(self, trace: LangfuseTrace, meta: dict[str, Any]) -> None:
        self._safe_ingest(
            [
                {
                    "id": _new_id(),
                    "type": "trace-create",
                    "timestamp": _now_iso(),
                    "body": {"id": trace.id, "metadata": meta},
                }
            ]
        )

    def _safe_ingest(self, batch: list[dict[str, Any]]) -> None:
        try:
            self._http.post(
                f"{self._host}{_INGESTION_PATH}",
                json={"batch": batch},
                headers={"Content-Type": "application/json"},
                auth=(self._public_key, self._secret_key),
            )
        except Exception:  # noqa: BLE001 - observability must never break the run
            return


def build_tracer(
    config: object | None = None,
    *,
    http: HttpPost | None = None,
    env: Mapping[str, str] | None = None,
) -> Tracer:
    """Return a `LangfuseTracer` when Langfuse env vars are present, else `NoOpTracer`.

    `config` is accepted for future extensibility (e.g. a `RunConfig` carrying
    explicit keys) but env vars are the primary source today.
    """
    source = env if env is not None else os.environ
    public_key = source.get("LANGFUSE_PUBLIC_KEY")
    secret_key = source.get("LANGFUSE_SECRET_KEY")
    host = source.get("LANGFUSE_HOST")

    if not public_key or not secret_key or not host:
        return NoOpTracer()

    return LangfuseTracer(public_key, secret_key, host, http=http)


__all__ = [
    "Tracer",
    "Trace",
    "Span",
    "NoOpTracer",
    "LangfuseTracer",
    "LangfuseTrace",
    "LangfuseSpan",
    "build_tracer",
]
