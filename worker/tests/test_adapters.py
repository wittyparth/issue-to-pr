from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from it2pr_worker.adapters.base import CoverageToolAbsentError, InferenceFailure
from it2pr_worker.adapters.node_adapter import NodeAdapter
from it2pr_worker.adapters.python_adapter import PythonAdapter
from it2pr_worker.adapters.registry import select_adapter


def _canned_runner(
    stdout: str = "", stderr: str = "", returncode: int = 0
) -> object:
    def runner(argv: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=list(argv), returncode=returncode, stdout=stdout, stderr=stderr
        )

    return runner


@pytest.fixture
def python_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "python-repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n")
    return repo


@pytest.fixture
def node_repo_pnpm(tmp_path: Path) -> Path:
    repo = tmp_path / "node-repo"
    repo.mkdir()
    (repo / "package.json").write_text('{"scripts": {"test": "vitest run"}}')
    (repo / "pnpm-lock.yaml").write_text("lockfileVersion: 6")
    return repo


@pytest.fixture
def node_repo_npm(tmp_path: Path) -> Path:
    repo = tmp_path / "node-repo-npm"
    repo.mkdir()
    (repo / "package.json").write_text('{"scripts": {"test": "jest"}}')
    (repo / "package-lock.json").write_text("{}")
    return repo


@pytest.fixture
def node_repo_yarn(tmp_path: Path) -> Path:
    repo = tmp_path / "node-repo-yarn"
    repo.mkdir()
    (repo / "package.json").write_text('{"scripts": {"test": "jest"}}')
    (repo / "yarn.lock").write_text("# yarn lockfile")
    return repo


@pytest.fixture
def empty_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "empty-repo"
    repo.mkdir()
    return repo


def test_python_adapter_detects_pyproject(python_repo: Path) -> None:
    adapter = PythonAdapter()
    assert adapter.detect(python_repo) is True


def test_node_adapter_detects_package_json(node_repo_pnpm: Path) -> None:
    adapter = NodeAdapter()
    assert adapter.detect(node_repo_pnpm) is True


def test_empty_dir_not_detected_by_either_adapter(empty_repo: Path) -> None:
    assert PythonAdapter().detect(empty_repo) is False
    assert NodeAdapter().detect(empty_repo) is False


def test_select_adapter_picks_python(python_repo: Path) -> None:
    adapter = select_adapter(python_repo)
    assert isinstance(adapter, PythonAdapter)


def test_select_adapter_picks_node(node_repo_pnpm: Path) -> None:
    adapter = select_adapter(node_repo_pnpm)
    assert isinstance(adapter, NodeAdapter)


def test_select_adapter_returns_unsupported_repo_for_empty_dir(empty_repo: Path) -> None:
    result = select_adapter(empty_repo)
    assert isinstance(result, InferenceFailure)
    assert result.reason.value == "unsupported_repo"


def test_node_package_manager_pnpm(node_repo_pnpm: Path) -> None:
    adapter = NodeAdapter()
    assert adapter._package_manager(node_repo_pnpm) == "pnpm"


def test_node_package_manager_yarn(node_repo_yarn: Path) -> None:
    adapter = NodeAdapter()
    assert adapter._package_manager(node_repo_yarn) == "yarn"


def test_node_package_manager_npm_default(node_repo_npm: Path) -> None:
    adapter = NodeAdapter()
    assert adapter._package_manager(node_repo_npm) == "npm"


def test_python_coverage_absent_raises(python_repo: Path) -> None:
    adapter = PythonAdapter()
    runner = _canned_runner(
        stdout="", stderr="/bin/sh: coverage: command not found", returncode=127
    )

    with pytest.raises(CoverageToolAbsentError):
        adapter.coverage(python_repo, runner=runner)


def test_python_coverage_parses_percentage(python_repo: Path) -> None:
    adapter = PythonAdapter()

    run_calls: list[list[str]] = []

    def runner(argv: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        run_calls.append(list(argv))
        if "report" in argv:
            report_stdout = (
                "Name    Stmts   Miss  Cover\n"
                "-----------------------------\n"
                "TOTAL      10      2    80%\n"
            )
            return subprocess.CompletedProcess(
                args=list(argv),
                returncode=0,
                stdout=report_stdout,
                stderr="",
            )
        return subprocess.CompletedProcess(args=list(argv), returncode=0, stdout="", stderr="")

    pct = adapter.coverage(python_repo, runner=runner)
    assert pct == 80.0


def test_python_coverage_parses_fractional_percentage(python_repo: Path) -> None:
    adapter = PythonAdapter()

    def runner(argv: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if "report" in argv:
            report_stdout = (
                "Name    Stmts   Miss  Cover\n"
                "-----------------------------\n"
                "TOTAL      10      0    95.00%\n"
            )
            return subprocess.CompletedProcess(
                args=list(argv), returncode=0, stdout=report_stdout, stderr=""
            )
        return subprocess.CompletedProcess(args=list(argv), returncode=0, stdout="", stderr="")

    assert adapter.coverage(python_repo, runner=runner) == 95.0


def test_python_coverage_parses_integer_percentage(python_repo: Path) -> None:
    adapter = PythonAdapter()

    def runner(argv: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if "report" in argv:
            report_stdout = "TOTAL      10      0    95%\n"
            return subprocess.CompletedProcess(
                args=list(argv), returncode=0, stdout=report_stdout, stderr=""
            )
        return subprocess.CompletedProcess(args=list(argv), returncode=0, stdout="", stderr="")

    assert adapter.coverage(python_repo, runner=runner) == 95.0


def test_node_coverage_absent_raises(node_repo_npm: Path) -> None:
    adapter = NodeAdapter()
    runner = _canned_runner(stdout="", stderr="c8: command not found", returncode=127)

    with pytest.raises(CoverageToolAbsentError):
        adapter.coverage(node_repo_npm, runner=runner)


def test_node_coverage_parses_percentage(node_repo_npm: Path) -> None:
    adapter = NodeAdapter()
    runner = _canned_runner(
        stdout="File      | % Stmts\nAll files |    85.5\n", stderr="", returncode=0
    )

    pct = adapter.coverage(node_repo_npm, runner=runner)
    assert pct == 85.5


def test_python_run_tests_uses_injected_runner_not_real_pytest(python_repo: Path) -> None:
    adapter = PythonAdapter()
    runner = _canned_runner(stdout="1 passed", stderr="", returncode=0)

    result = adapter.run_tests(python_repo, runner=runner)

    assert result.passed is True
    assert "1 passed" in result.output_tail


def test_node_run_tests_uses_injected_runner_not_real_npm(node_repo_npm: Path) -> None:
    adapter = NodeAdapter()
    runner = _canned_runner(stdout="", stderr="1 failing", returncode=1)

    result = adapter.run_tests(node_repo_npm, runner=runner)

    assert result.passed is False
    assert "1 failing" in result.output_tail
