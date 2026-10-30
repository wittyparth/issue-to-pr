"""Common types for language adapters.

Adapters detect a repo's language/toolchain, install dependencies, run the
test suite, and compute a coverage percentage. All process execution is via
an injectable `runner` callable so tests never actually install packages or
run the target repo's test suite.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

RunnerResult = subprocess.CompletedProcess[str]
Runner = Callable[[Sequence[str]], RunnerResult]


def default_runner(argv: Sequence[str], *, cwd: Path | str | None = None) -> RunnerResult:
    return subprocess.run(  # noqa: S603
        list(argv),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


@dataclass(frozen=True, slots=True)
class TestResult:
    passed: bool
    output_tail: str


class InferenceFailureReason(StrEnum):
    UNSUPPORTED_REPO = "unsupported_repo"
    COVERAGE_TOOL_ABSENT = "coverage_tool_absent"


@dataclass(frozen=True, slots=True)
class InferenceFailure:
    reason: InferenceFailureReason
    detail: str = ""


class CoverageToolAbsentError(RuntimeError):
    """Raised by an adapter's `coverage()` when no coverage tool is available."""

    def __init__(self, detail: str = "") -> None:
        super().__init__(detail or "coverage tool absent")
        self.detail = detail


@runtime_checkable
class LanguageAdapter(Protocol):
    name: str

    def detect(self, repo_dir: Path) -> bool: ...

    def install(self, repo_dir: Path, *, runner: Runner = default_runner) -> None: ...

    def test_command(self, repo_dir: Path) -> list[str]: ...

    def run_tests(self, repo_dir: Path, *, runner: Runner = default_runner) -> TestResult: ...

    def coverage(self, repo_dir: Path, *, runner: Runner = default_runner) -> float | None: ...
