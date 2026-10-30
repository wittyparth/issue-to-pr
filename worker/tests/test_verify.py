from __future__ import annotations

from pathlib import Path

from it2pr_worker.adapters.base import TestResult
from it2pr_worker.verify import verify_and_gate


class _FakeAdapter:
    name = "fake"

    def __init__(self, tests_passed: bool, head_coverage: float | None) -> None:
        self.tests_passed = tests_passed
        self.head_coverage = head_coverage

    def detect(self, repo_dir: Path) -> bool:
        return True

    def install(self, repo_dir: Path, *, runner=None) -> None:
        pass

    def test_command(self, repo_dir: Path) -> list[str]:
        return ["fake-test"]

    def run_tests(self, repo_dir: Path, *, runner=None) -> TestResult:
        return TestResult(passed=self.tests_passed, output_tail="")

    def coverage(self, repo_dir: Path, *, runner=None) -> float | None:
        return self.head_coverage


def test_red_tests_yield_comment_only() -> None:
    adapter = _FakeAdapter(tests_passed=False, head_coverage=None)

    result = verify_and_gate(Path("/tmp/repo"), adapter, base_coverage=90.0)

    assert result.tests_passed is False
    assert result.decision == "comment_only"
    assert result.head_coverage is None
    assert result.coverage_delta is None


def test_green_tests_no_coverage_drop_yields_open_pr() -> None:
    adapter = _FakeAdapter(tests_passed=True, head_coverage=91.0)

    result = verify_and_gate(Path("/tmp/repo"), adapter, base_coverage=90.0)

    assert result.tests_passed is True
    assert result.decision == "open_pr"
    assert result.coverage_delta == 1.0


def test_green_tests_with_coverage_drop_beyond_threshold_yields_needs_review() -> None:
    adapter = _FakeAdapter(tests_passed=True, head_coverage=80.0)

    result = verify_and_gate(
        Path("/tmp/repo"), adapter, base_coverage=90.0, coverage_drop_threshold=2.0
    )

    assert result.tests_passed is True
    assert result.decision == "open_pr_needs_review"
    assert result.coverage_delta == -10.0


def test_green_tests_with_small_coverage_drop_within_threshold_yields_open_pr() -> None:
    adapter = _FakeAdapter(tests_passed=True, head_coverage=89.0)

    result = verify_and_gate(
        Path("/tmp/repo"), adapter, base_coverage=90.0, coverage_drop_threshold=2.0
    )

    assert result.decision == "open_pr"
    assert result.coverage_delta == -1.0


def test_undeterminable_head_coverage_with_base_fails_closed() -> None:
    # head_coverage parse miss (None) while a base exists must NOT open a normal
    # PR: it could be hiding a regression, so fail closed to needs-review.
    adapter = _FakeAdapter(tests_passed=True, head_coverage=None)

    result = verify_and_gate(Path("/tmp/repo"), adapter, base_coverage=90.0)

    assert result.tests_passed is True
    assert result.head_coverage is None
    assert result.coverage_delta is None
    assert result.decision == "open_pr_needs_review"


def test_unknown_base_coverage_does_not_trigger_needs_review() -> None:
    adapter = _FakeAdapter(tests_passed=True, head_coverage=50.0)

    result = verify_and_gate(Path("/tmp/repo"), adapter, base_coverage=None)

    assert result.decision == "open_pr"
    assert result.coverage_delta is None
