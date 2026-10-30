"""Markdown report generation for an `EvalRun`.

Renders a per-issue table, summary stats, and a pass-rate-vs-floor verdict.
Per the split-latency note (M8), the report surfaces both the p50 time-to-PR
AND the raw latency distribution — the seeded set is only 10-15 issues, so a
single p50 number is coarse and can hide a bimodal distribution.
"""

from __future__ import annotations

import statistics
from pathlib import Path

from it2pr_eval.config import EvalConfig
from it2pr_eval.runner import EvalRun

_COMPARISON_ALTERNATIVE = "Cursor Background Agents"


def _fmt_cost(cost_usd: float | None) -> str:
    return f"${cost_usd:.2f}" if cost_usd is not None else "n/a"


def _fmt_seconds(seconds: float) -> str:
    return f"{seconds:.1f}s"


def _render_issue_table(eval_run: EvalRun) -> str:
    issues_by_id = eval_run.issues_by_id
    header = (
        "| Issue | Language | Difficulty | Result | Cost | Time-to-first-action | Time-to-PR |\n"
        "|---|---|---|---|---|---|---|\n"
    )
    rows = []
    for outcome in eval_run.outcomes:
        issue = issues_by_id.get(outcome.issue_id)
        language = issue.language if issue else "unknown"
        difficulty = issue.difficulty if issue else "unknown"
        result = "PASS" if outcome.passed else "FAIL"
        rows.append(
            f"| {outcome.issue_id} | {language} | {difficulty} | {result} | "
            f"{_fmt_cost(outcome.cost_usd)} | "
            f"{_fmt_seconds(outcome.time_to_first_action_s)} | "
            f"{_fmt_seconds(outcome.time_to_pr_s)} |"
        )
    return header + "\n".join(rows) + ("\n" if rows else "")


def _render_summary(eval_run: EvalRun, config: EvalConfig) -> str:
    outcomes = eval_run.outcomes
    pass_count = eval_run.pass_count
    total = eval_run.total_count
    verdict = "PASS" if eval_run.meets_floor else "FAIL"

    costs = [o.cost_usd for o in outcomes if o.cost_usd is not None]
    total_cost = sum(costs) if costs else 0.0
    mean_cost = (total_cost / len(costs)) if costs else None

    pr_latencies = sorted(o.time_to_pr_s for o in outcomes)
    p50 = statistics.median(pr_latencies) if pr_latencies else None
    mean_first_action = (
        statistics.mean(o.time_to_first_action_s for o in outcomes) if outcomes else None
    )

    distribution = ", ".join(_fmt_seconds(v) for v in pr_latencies) if pr_latencies else "n/a"

    lines = [
        "## Summary",
        "",
        f"- Pass rate: {pass_count}/{total} (floor: {config.pass_rate_floor}) — **{verdict}**",
        f"- Total cost: {_fmt_cost(total_cost if costs else None)}",
        f"- Mean cost per PR: {_fmt_cost(mean_cost)}",
        f"- p50 time-to-PR: {_fmt_seconds(p50) if p50 is not None else 'n/a'}",
        f"- Raw time-to-PR distribution (s): {distribution}",
        (
            f"- Mean time-to-first-action: "
            f"{_fmt_seconds(mean_first_action) if mean_first_action is not None else 'n/a'}"
        ),
    ]
    return "\n".join(lines) + "\n"


def _render_comparison(config: EvalConfig) -> str:
    return (
        "## Comparison\n\n"
        f"- vs {_COMPARISON_ALTERNATIVE}: _placeholder — fill in after a live run on shared "
        f"issues (pass rate, cost/PR, time-to-PR for {_COMPARISON_ALTERNATIVE} vs this "
        f"harness at model={config.model}, prompt={config.prompt_version})._\n"
    )


def render_report(eval_run: EvalRun, config: EvalConfig) -> str:
    """Render a Markdown eval report for `eval_run` under reproducibility `config`."""
    parts = [
        "# Issue-to-PR Eval Report",
        "",
        (
            f"Model: `{config.model}` · Temperature: `{config.temperature}` · "
            f"Prompt version: `{config.prompt_version}`"
        ),
        "",
        "## Per-Issue Results",
        "",
        _render_issue_table(eval_run),
        _render_summary(eval_run, config),
        _render_comparison(config),
    ]
    return "\n".join(parts)


def write_report(
    eval_run: EvalRun, config: EvalConfig, path: Path | str = "eval/REPORT.md"
) -> Path:
    """Render and write the report to `path`, returning the written path."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_report(eval_run, config), encoding="utf-8")
    return output_path
