from __future__ import annotations

import threading
from dataclasses import dataclass, field

from it2pr_eval.config import EvalConfig, FixtureRepo
from it2pr_eval.fixtures import SeedIssue
from it2pr_eval.runner import RunOutcome, run_eval


def _make_config(pass_rate_floor: int = 1) -> EvalConfig:
    return EvalConfig(
        model="m",
        temperature=0.0,
        prompt_version="v1",
        fixture_repos=[FixtureRepo(full_name="org/repo", commit_sha="abc123", language="python")],
        pass_rate_floor=pass_rate_floor,
    )


def _make_issues(n: int) -> list[SeedIssue]:
    return [
        SeedIssue(
            id=f"issue-{i:02d}",
            repo="org/repo",
            commit_sha="abc123",
            issue_number=i,
            difficulty="easy",
            language="python",
            expected_outcome="fix",
        )
        for i in range(n)
    ]


@dataclass
class _ScriptedTrigger:
    """Fake trigger returning a pre-scripted outcome per issue id."""

    outcomes_by_id: dict[str, RunOutcome]
    concurrent_calls: list[int] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _active: int = 0

    def run(self, issue: SeedIssue) -> RunOutcome:
        with self._lock:
            self._active += 1
            self.concurrent_calls.append(self._active)
        try:
            return self.outcomes_by_id[issue.id]
        finally:
            with self._lock:
                self._active -= 1


def test_run_eval_aggregates_scripted_outcomes() -> None:
    issues = _make_issues(3)
    outcomes = {
        "issue-00": RunOutcome("issue-00", True, 1.0, 1.0, 10.0, "https://pr/0"),
        "issue-01": RunOutcome("issue-01", False, 2.0, 2.0, 20.0, None),
        "issue-02": RunOutcome("issue-02", True, 3.0, 3.0, 30.0, "https://pr/2"),
    }
    trigger = _ScriptedTrigger(outcomes_by_id=outcomes)
    config = _make_config(pass_rate_floor=2)

    eval_run = run_eval(config, issues, trigger, concurrency=1)

    assert eval_run.total_count == 3
    assert eval_run.pass_count == 2
    assert eval_run.meets_floor is True
    assert [o.issue_id for o in eval_run.outcomes] == ["issue-00", "issue-01", "issue-02"]


def test_run_eval_below_floor_does_not_meet_floor() -> None:
    issues = _make_issues(3)
    outcomes = {
        "issue-00": RunOutcome("issue-00", False, 1.0, 1.0, 10.0, None),
        "issue-01": RunOutcome("issue-01", False, 2.0, 2.0, 20.0, None),
        "issue-02": RunOutcome("issue-02", True, 3.0, 3.0, 30.0, "https://pr/2"),
    }
    trigger = _ScriptedTrigger(outcomes_by_id=outcomes)
    config = _make_config(pass_rate_floor=2)

    eval_run = run_eval(config, issues, trigger, concurrency=1)

    assert eval_run.pass_count == 1
    assert eval_run.meets_floor is False


def test_concurrency_is_capped_at_eight() -> None:
    n = 20
    issues = _make_issues(n)
    outcomes = {
        issue.id: RunOutcome(issue.id, True, 1.0, 1.0, 1.0, "https://pr") for issue in issues
    }
    trigger = _ScriptedTrigger(outcomes_by_id=outcomes)
    config = _make_config()

    run_eval(config, issues, trigger, concurrency=999)

    assert max(trigger.concurrent_calls) <= 8


def test_reproducibility_same_inputs_yield_identical_pass_fail_set_and_order() -> None:
    issues = _make_issues(5)
    outcomes = {
        issue.id: RunOutcome(
            issue.id, i % 2 == 0, 1.0, 1.0, float(i), "https://pr" if i % 2 == 0 else None
        )
        for i, issue in enumerate(issues)
    }
    config = _make_config(pass_rate_floor=2)

    trigger_a = _ScriptedTrigger(outcomes_by_id=dict(outcomes))
    trigger_b = _ScriptedTrigger(outcomes_by_id=dict(outcomes))

    run_a = run_eval(config, issues, trigger_a, concurrency=4)
    run_b = run_eval(config, issues, trigger_b, concurrency=4)

    ids_a = [o.issue_id for o in run_a.outcomes]
    ids_b = [o.issue_id for o in run_b.outcomes]
    passed_a = [o.passed for o in run_a.outcomes]
    passed_b = [o.passed for o in run_b.outcomes]

    assert ids_a == ids_b
    assert passed_a == passed_b
    assert run_a.pass_count == run_b.pass_count
