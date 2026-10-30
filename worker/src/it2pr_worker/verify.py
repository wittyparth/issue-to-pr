"""Verification gate (M5, Principle 3: verification is the gate).

Runs the full test suite and head coverage via the injected `LanguageAdapter`
and decides whether a PR should open, open with a `needs-review` label, or
only a comment should be posted. The agent's own claim of success is never
trusted; only a green in-sandbox run can open a PR.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from it2pr_worker.adapters.base import LanguageAdapter, Runner
from it2pr_worker.adapters.base import default_runner as _default_runner

Decision = Literal["open_pr", "open_pr_needs_review", "comment_only"]


@dataclass(frozen=True, slots=True)
class VerifyResult:
    tests_passed: bool
    head_coverage: float | None
    coverage_delta: float | None
    decision: Decision
    test_output_tail: str = ""


def verify_and_gate(
    repo_dir: Path,
    adapter: LanguageAdapter,
    base_coverage: float | None,
    *,
    coverage_drop_threshold: float = 2.0,
    runner: Runner = _default_runner,
) -> VerifyResult:
    """Run the full suite + head coverage and decide the PR-posting outcome.

    Rules:
    - Tests red -> `comment_only` (no PR opens, regardless of coverage).
    - Tests green and coverage dropped beyond `coverage_drop_threshold` (in
      percentage points) relative to `base_coverage` -> `open_pr_needs_review`.
    - Tests green but coverage cannot be determined while a base exists (head
      coverage failed to parse) -> `open_pr_needs_review`. Fail CLOSED: an
      undeterminable coverage could be hiding a real regression, so it must not
      silently open a normal PR.
    - Tests green otherwise -> `open_pr`.
    """
    test_result = adapter.run_tests(repo_dir, runner=runner)

    if not test_result.passed:
        return VerifyResult(
            tests_passed=False,
            head_coverage=None,
            coverage_delta=None,
            decision="comment_only",
            test_output_tail=test_result.output_tail,
        )

    head_coverage = adapter.coverage(repo_dir, runner=runner)

    coverage_delta: float | None = None
    if head_coverage is not None and base_coverage is not None:
        coverage_delta = head_coverage - base_coverage

    decision: Decision = "open_pr"
    if coverage_delta is not None and coverage_delta <= -coverage_drop_threshold:
        decision = "open_pr_needs_review"
    elif base_coverage is not None and head_coverage is None:
        # Coverage indeterminable (parse miss) but a base existed: fail closed.
        decision = "open_pr_needs_review"

    return VerifyResult(
        tests_passed=True,
        head_coverage=head_coverage,
        coverage_delta=coverage_delta,
        decision=decision,
    )
