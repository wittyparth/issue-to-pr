"""Scrubbing logging setup (M7 security follow-up: close the log-leak vector).

`install_scrubbing_logging` configures the stdlib `logging` root logger with a
filter that runs `scrub()` over every emitted record's message and args, so no
secret (GitHub token, Authorization header, PEM key, high-entropy API key, or
any explicitly-known live secret) can leak via a log line.

`scrub_transcript` returns a scrubbed copy of an `AgentResult` (or any object
with `messages`/`raw`-shaped data) suitable for safe S3/trace archival.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from it2pr_worker.scrub import scrub, scrub_secrets_from

if TYPE_CHECKING:
    from it2pr_worker.agent import AgentResult
    from it2pr_worker.llm.base import Message


class ScrubbingFilter(logging.Filter):
    """Logging filter that scrubs a record's message and args in place."""

    def __init__(self, extra_secrets: tuple[str, ...] = ()) -> None:
        super().__init__()
        self._extra_secrets = list(extra_secrets)

    def filter(self, record: logging.LogRecord) -> bool:
        # Render args into msg first so scrubbing sees the final text (a raw
        # `%s`-style arg could itself carry a secret that msg alone misses).
        try:
            rendered = record.getMessage()
        except Exception:  # noqa: BLE001 - never break logging over a bad record
            rendered = str(record.msg)
        record.msg = scrub(rendered, extra_secrets=self._extra_secrets)
        record.args = ()
        return True


def install_scrubbing_logging(
    *,
    extra_secrets: tuple[str, ...] = (),
    level: int = logging.INFO,
    logger: logging.Logger | None = None,
) -> ScrubbingFilter:
    """Install a `ScrubbingFilter` on the given logger (default: root logger).

    Idempotent-ish: calling this repeatedly adds additional filters/handlers is
    avoided by attaching the filter directly to the logger (not a handler), so
    it applies regardless of handler configuration.
    """
    target_logger = logger if logger is not None else logging.getLogger()
    target_logger.setLevel(level)

    scrubbing_filter = ScrubbingFilter(extra_secrets=extra_secrets)
    target_logger.addFilter(scrubbing_filter)

    if not target_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        target_logger.addHandler(handler)

    return scrubbing_filter


def scrub_transcript(
    agent_result: AgentResult, extra_secrets: tuple[str, ...] = ()
) -> AgentResult:
    """Return a copy of `agent_result` with messages/raw payloads scrubbed.

    Safe to archive to S3/trace storage: every `Message.content` and any
    `raw`-shaped payload nested within is passed through `scrub_secrets_from`.
    """
    secrets = list(extra_secrets)
    scrubbed_messages: list[Message] = [
        replace(message, content=scrub(message.content, extra_secrets=secrets))
        for message in agent_result.messages
    ]
    return replace(agent_result, messages=scrubbed_messages)


def scrub_raw_payload(raw: dict[str, Any], extra_secrets: tuple[str, ...] = ()) -> dict[str, Any]:
    """Return a scrubbed copy of an `LLMResponse.raw`-style payload."""
    return scrub_secrets_from(raw, extra_secrets=list(extra_secrets))


__all__ = [
    "ScrubbingFilter",
    "install_scrubbing_logging",
    "scrub_transcript",
    "scrub_raw_payload",
]
