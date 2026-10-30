from __future__ import annotations

from it2pr_eval.config import EvalConfig, FixtureRepo
from it2pr_eval.fixtures import SeedIssue
from it2pr_eval.report import render_report
from it2pr_eval.runner import EvalRun, RunOutcome


def _make_config(pass_rate_floor: int) -> EvalConfig:
    return EvalConfig(
        model="test-model",
        temperature=0.0,
        prompt_version="v1",
        fixture_repos=[FixtureRepo(full_name="org/repo", commit_sha="abc123", language="python")],
        pass_rate_floor=pass_rate_floor,
    )


def _make_issue(issue_id: str, language: str, difficulty: str) -> SeedIssue:
    return SeedIssue(
        id=issue_id,
        repo="org/repo",
        commit_sha="abc123",
        issue_number=1,
        difficulty=difficulty,  # type: ignore[arg-type]
        language=language,
        expected_outcome="fix",
    )


def _make_eval_run(config: EvalConfig, pass_flags: list[bool]) -> EvalRun:
    issues = [
        _make_issue(f"issue-{i:02d}", "python" if i % 2 == 0 else "node", "easy")
        for i in range(len(pass_flags))
    ]
    outcomes = [
        RunOutcome(
            issue_id=issue.id,
            passed=passed,
            cost_usd=1.5 + i,
            time_to_first_action_s=5.0 + i,
            time_to_pr_s=100.0 + i * 10,
            pr_url=f"https://pr/{i}" if passed else None,
        )
        for i, (issue, passed) in enumerate(zip(issues, pass_flags, strict=True))
    ]
    return EvalRun(config=config, outcomes=outcomes, issues=issues)


def test_report_contains_per_issue_table() -> None:
    config = _make_config(pass_rate_floor=1)
    eval_run = _make_eval_run(config, [True, False])

    report = render_report(eval_run, config)

    assert "| Issue | Language | Difficulty | Result | Cost |" in report
    assert "issue-00" in report
    assert "issue-01" in report
    assert "PASS" in report
    assert "FAIL" in report


def test_report_verdict_pass_when_at_or_above_floor() -> None:
    config = _make_config(pass_rate_floor=2)
    eval_run = _make_eval_run(config, [True, True, False])

    report = render_report(eval_run, config)

    assert "Pass rate: 2/3 (floor: 2) — **PASS**" in report


def test_report_verdict_fail_when_below_floor() -> None:
    config = _make_config(pass_rate_floor=3)
    eval_run = _make_eval_run(config, [True, True, False])

    report = render_report(eval_run, config)

    assert "Pass rate: 2/3 (floor: 3) — **FAIL**" in report


def test_report_contains_p50_and_raw_distribution() -> None:
    config = _make_config(pass_rate_floor=1)
    eval_run = _make_eval_run(config, [True, True, True])

    report = render_report(eval_run, config)

    assert "p50 time-to-PR" in report
    assert "Raw time-to-PR distribution" in report
    for outcome in eval_run.outcomes:
        assert f"{outcome.time_to_pr_s:.1f}s" in report


def test_report_contains_comparison_line() -> None:
    config = _make_config(pass_rate_floor=1)
    eval_run = _make_eval_run(config, [True])

    report = render_report(eval_run, config)

    assert "Comparison" in report
    assert "Cursor Background Agents" in report
