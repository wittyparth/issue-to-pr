"""PR body template (M5, CRITICAL-4).

Renders a bounded template with rationale, diff summary, coverage delta,
cost, turns, and trace URL; scrubs secrets from every field (an LLM
rationale can echo issue/tool content that may itself contain a leaked
secret); and truncates to at most `MAX_BODY_CHARS` so `create_pull` never
422s on GitHub's body-size limit. The diff-summary section is truncated
first, with a "(truncated)" marker appended, since it is the section most
likely to be large.
"""

from __future__ import annotations

from it2pr_worker.scrub import scrub

MAX_BODY_CHARS = 60000
_TRUNCATION_MARKER = "\n\n... (truncated)\n"


def _format_coverage_delta(coverage_delta: float | None) -> str:
    if coverage_delta is None:
        return "unknown"
    sign = "+" if coverage_delta >= 0 else ""
    return f"{sign}{coverage_delta:.2f}%"


def _format_cost(cost_usd: float | None) -> str:
    if cost_usd is None:
        return "unknown"
    return f"${cost_usd:.4f}"


def build_pr_body(
    *,
    rationale: str,
    diff_summary: str,
    coverage_delta: float | None,
    cost_usd: float | None,
    turns: int,
    trace_url: str,
    extra_secrets: list[str] | None = None,
) -> str:
    """Render, scrub, and size-bound the PR body."""
    scrubbed_rationale = scrub(rationale, extra_secrets=extra_secrets)
    scrubbed_diff_summary = scrub(diff_summary, extra_secrets=extra_secrets)
    scrubbed_trace_url = scrub(trace_url, extra_secrets=extra_secrets)

    body = _render(
        rationale=scrubbed_rationale,
        diff_summary=scrubbed_diff_summary,
        coverage_delta=coverage_delta,
        cost_usd=cost_usd,
        turns=turns,
        trace_url=scrubbed_trace_url,
    )

    if len(body) <= MAX_BODY_CHARS:
        return body

    # Truncate the diff-summary section first: compute how much room is left
    # for it once every other section is rendered at full size.
    empty_diff_body = _render(
        rationale=scrubbed_rationale,
        diff_summary="",
        coverage_delta=coverage_delta,
        cost_usd=cost_usd,
        turns=turns,
        trace_url=scrubbed_trace_url,
    )
    overhead = len(empty_diff_body) + len(_TRUNCATION_MARKER)
    budget = max(MAX_BODY_CHARS - overhead, 0)
    truncated_diff_summary = scrubbed_diff_summary[:budget] + _TRUNCATION_MARKER

    body = _render(
        rationale=scrubbed_rationale,
        diff_summary=truncated_diff_summary,
        coverage_delta=coverage_delta,
        cost_usd=cost_usd,
        turns=turns,
        trace_url=scrubbed_trace_url,
    )

    if len(body) > MAX_BODY_CHARS:
        body = body[: MAX_BODY_CHARS - len(_TRUNCATION_MARKER)] + _TRUNCATION_MARKER

    return body


def _render(
    *,
    rationale: str,
    diff_summary: str,
    coverage_delta: float | None,
    cost_usd: float | None,
    turns: int,
    trace_url: str,
) -> str:
    return (
        "## Rationale\n"
        f"{rationale}\n\n"
        "## Diff summary\n"
        f"{diff_summary}\n\n"
        "## Coverage delta\n"
        f"{_format_coverage_delta(coverage_delta)}\n\n"
        "## Cost\n"
        f"{_format_cost(cost_usd)}\n\n"
        "## Turns\n"
        f"{turns}\n\n"
        "## Trace\n"
        f"{trace_url}\n"
    )
