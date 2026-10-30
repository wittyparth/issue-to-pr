from __future__ import annotations

from it2pr_worker.pr_body import MAX_BODY_CHARS, build_pr_body


def test_body_contains_all_fields() -> None:
    body = build_pr_body(
        rationale="Fixed the null check in the parser.",
        diff_summary=" src/parser.py | 4 +++-\n 1 file changed",
        coverage_delta=1.5,
        cost_usd=0.42,
        turns=3,
        trace_url="https://langfuse.example.com/trace/abc",
    )

    assert "Fixed the null check in the parser." in body
    assert "src/parser.py" in body
    assert "+1.50%" in body
    assert "$0.4200" in body
    assert "3" in body
    assert "https://langfuse.example.com/trace/abc" in body


def test_body_handles_unknown_coverage_and_cost() -> None:
    body = build_pr_body(
        rationale="x",
        diff_summary="y",
        coverage_delta=None,
        cost_usd=None,
        turns=1,
        trace_url="https://trace",
    )

    assert "unknown" in body


def test_huge_diff_summary_is_truncated_with_marker() -> None:
    huge_diff = "line changed\n" * 20000  # far more than 60000 chars

    body = build_pr_body(
        rationale="rationale text",
        diff_summary=huge_diff,
        coverage_delta=0.0,
        cost_usd=1.0,
        turns=5,
        trace_url="https://trace",
    )

    assert len(body) <= MAX_BODY_CHARS
    assert "(truncated)" in body
    assert "rationale text" in body


def test_secret_in_rationale_is_redacted() -> None:
    body = build_pr_body(
        rationale="Used token ghs_abcdefghij1234567890 to test the fix.",
        diff_summary="diff",
        coverage_delta=0.0,
        cost_usd=0.1,
        turns=1,
        trace_url="https://trace",
    )

    assert "ghs_abcdefghij1234567890" not in body
    assert "***REDACTED***" in body


def test_extra_secret_redacted_from_all_fields() -> None:
    live_token = "live-installation-token-value-xyz"
    body = build_pr_body(
        rationale=f"used {live_token} during the run",
        diff_summary=f"context mentions {live_token}",
        coverage_delta=0.0,
        cost_usd=0.1,
        turns=1,
        trace_url="https://trace",
        extra_secrets=[live_token],
    )

    assert live_token not in body
