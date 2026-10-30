from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from it2pr_worker.adapters.base import TestResult
from it2pr_worker.coverage_base import get_base_coverage


class _FakeAdapter:
    name = "fake"

    def __init__(self, coverage_value: float | None) -> None:
        self.coverage_value = coverage_value
        self.coverage_calls = 0

    def detect(self, repo_dir: Path) -> bool:
        return True

    def install(self, repo_dir: Path, *, runner=None) -> None:
        pass

    def test_command(self, repo_dir: Path) -> list[str]:
        return ["fake-test"]

    def run_tests(self, repo_dir: Path, *, runner=None) -> TestResult:
        return TestResult(passed=True, output_tail="")

    def coverage(self, repo_dir: Path, *, runner=None) -> float | None:
        self.coverage_calls += 1
        return self.coverage_value


class _FakeCache:
    def __init__(self, initial: dict[str, float | None] | None = None) -> None:
        self.store: dict[str, float | None] = dict(initial or {})
        self.set_calls: list[tuple[str, float | None]] = []

    def get(self, base_sha: str) -> float | None:
        return self.store.get(base_sha)

    def set(self, base_sha: str, coverage: float | None) -> None:
        self.set_calls.append((base_sha, coverage))
        self.store[base_sha] = coverage


class _RecordingGitRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(args=list(argv), returncode=0, stdout="", stderr="")


def test_cache_hit_returns_cached_value_without_running() -> None:
    adapter = _FakeAdapter(coverage_value=99.9)
    cache = _FakeCache(initial={"abc123": 87.5})
    git_runner = _RecordingGitRunner()

    result = get_base_coverage(
        Path("/tmp/repo"), "abc123", adapter, cache=cache, git_runner=git_runner
    )

    assert result == 87.5
    assert adapter.coverage_calls == 0
    assert git_runner.calls == []


def test_cache_miss_runs_and_stores() -> None:
    adapter = _FakeAdapter(coverage_value=72.3)
    cache = _FakeCache()
    git_runner = _RecordingGitRunner()

    result = get_base_coverage(
        Path("/tmp/repo"), "def456", adapter, cache=cache, git_runner=git_runner
    )

    assert result == 72.3
    assert adapter.coverage_calls == 1
    assert cache.set_calls == [("def456", 72.3)]
    assert git_runner.calls  # checked out the base ref
    assert "def456" in git_runner.calls[0]


def test_no_cache_always_runs() -> None:
    adapter = _FakeAdapter(coverage_value=50.0)
    git_runner = _RecordingGitRunner()

    result = get_base_coverage(Path("/tmp/repo"), "sha1", adapter, git_runner=git_runner)

    assert result == 50.0
    assert adapter.coverage_calls == 1
