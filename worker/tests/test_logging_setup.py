from __future__ import annotations

import logging

from it2pr_worker.agent import AgentResult
from it2pr_worker.llm.base import Message
from it2pr_worker.logging_setup import (
    install_scrubbing_logging,
    scrub_raw_payload,
    scrub_transcript,
)


def _make_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.filters.clear()
    logger.propagate = False
    return logger


def test_log_line_with_github_token_is_scrubbed(caplog: object) -> None:
    logger = _make_logger("test_logging_setup.token")
    handler = logging.Handler()
    records: list[logging.LogRecord] = []
    handler.emit = records.append  # type: ignore[method-assign]
    logger.addHandler(handler)

    install_scrubbing_logging(logger=logger)
    logger.info("minted token ghs_abcdefghij1234567890ABCDEFGHIJ")

    assert len(records) == 1
    message = records[0].getMessage()
    assert "ghs_" not in message
    assert "***REDACTED***" in message


def test_log_line_with_bearer_token_is_scrubbed() -> None:
    logger = _make_logger("test_logging_setup.bearer")
    handler = logging.Handler()
    records: list[logging.LogRecord] = []
    handler.emit = records.append  # type: ignore[method-assign]
    logger.addHandler(handler)

    install_scrubbing_logging(logger=logger)
    logger.info("calling api with %s", "Authorization: Bearer sometoken1234567890abcdef")

    assert len(records) == 1
    message = records[0].getMessage()
    assert "sometoken1234567890abcdef" not in message
    assert "***REDACTED***" in message


def test_scrub_transcript_redacts_messages() -> None:
    result = AgentResult(
        status="finished",
        turns=1,
        cost_usd=0.1,
        summary="fixed it",
        messages=[
            Message(role="assistant", content="using token ghs_abcdefghij1234567890ABCDEFGHIJ"),
            Message(role="user", content="plain text, no secrets here"),
        ],
    )

    scrubbed = scrub_transcript(result)

    assert "ghs_" not in scrubbed.messages[0].content
    assert "***REDACTED***" in scrubbed.messages[0].content
    assert scrubbed.messages[1].content == "plain text, no secrets here"
    # Original is untouched.
    assert "ghs_" in result.messages[0].content


def test_scrub_transcript_redacts_extra_secrets() -> None:
    live_token = "live-installation-token-xyz"
    result = AgentResult(
        status="finished",
        turns=1,
        cost_usd=None,
        summary="done",
        messages=[Message(role="tool", content=f"pushed with {live_token}")],
    )

    scrubbed = scrub_transcript(result, extra_secrets=(live_token,))

    assert live_token not in scrubbed.messages[0].content


def test_scrub_raw_payload_redacts_nested_secrets() -> None:
    raw = {
        "choices": [{"message": {"content": "here is ghs_abcdefghij1234567890ABCDEFGHIJ"}}],
        "headers": {"Authorization": "Authorization: Bearer sometoken1234567890abcdef"},
    }

    scrubbed = scrub_raw_payload(raw)

    assert "ghs_" not in scrubbed["choices"][0]["message"]["content"]
    assert "sometoken1234567890abcdef" not in scrubbed["headers"]["Authorization"]
