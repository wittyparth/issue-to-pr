from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from it2pr_worker.adapters.base import TestResult
from it2pr_worker.agent.tools import (
    ToolContext,
    build_toolset,
    dispatch,
)
from it2pr_worker.llm.base import ToolCall


def _ctx(repo: Path, **kw: object) -> ToolContext:
    return ToolContext(repo_dir=repo, **kw)  # type: ignore[arg-type]


def _call(name: str, **args: object) -> ToolCall:
    return ToolCall(id=f"call_{name}", name=name, arguments=dict(args))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    (r / "src.py").write_text("print('hello')\n")
    (r / ".github" / "workflows").mkdir(parents=True)
    (r / ".github" / "workflows" / "ci.yml").write_text("on: push\n")
    return r


def test_allowlist_rejects_workflow_edit_and_does_not_write(repo: Path) -> None:
    original = (repo / ".github" / "workflows" / "ci.yml").read_text()
    result = dispatch(
        _call("edit_file", path=".github/workflows/ci.yml", old_str="push", new_str="hacked"),
        _ctx(repo),
    )
    assert result.ok is False
    assert "workflows" in result.content
    # File must be untouched.
    assert (repo / ".github" / "workflows" / "ci.yml").read_text() == original


def test_allowlist_rejects_workflow_apply_patch(repo: Path) -> None:
    original = (repo / ".github" / "workflows" / "ci.yml").read_text()
    result = dispatch(
        _call("apply_patch", path=".github/workflows/ci.yml", content="on: nothing\n"),
        _ctx(repo),
    )
    assert result.ok is False
    assert (repo / ".github" / "workflows" / "ci.yml").read_text() == original


def test_edit_file_applies_old_to_new(repo: Path) -> None:
    result = dispatch(
        _call("edit_file", path="src.py", old_str="hello", new_str="world"),
        _ctx(repo),
    )
    assert result.ok is True
    assert (repo / "src.py").read_text() == "print('world')\n"


def test_edit_file_reports_missing_old_str(repo: Path) -> None:
    result = dispatch(
        _call("edit_file", path="src.py", old_str="nope", new_str="x"),
        _ctx(repo),
    )
    assert result.ok is False
    assert "old_str not found" in result.content


def test_read_file_rejects_path_traversal(repo: Path) -> None:
    result = dispatch(
        _call("read_file", path="../../etc/passwd"),
        _ctx(repo),
    )
    assert result.ok is False
    assert "escapes repo_dir" in result.content


def test_read_file_reads_within_repo(repo: Path) -> None:
    result = dispatch(_call("read_file", path="src.py"), _ctx(repo))
    assert result.ok is True
    assert "hello" in result.content


def test_read_file_line_range(repo: Path) -> None:
    (repo / "multi.txt").write_text("a\nb\nc\nd\n")
    result = dispatch(
        _call("read_file", path="multi.txt", start=2, end=3),
        _ctx(repo),
    )
    assert result.ok is True
    assert result.content == "b\nc"


def test_edit_file_rejects_traversal_and_does_not_write(repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    result = dispatch(
        _call("edit_file", path="../outside.txt", old_str="secret", new_str="x"),
        _ctx(repo),
    )
    assert result.ok is False
    assert outside.read_text() == "secret"


def test_run_tests_delegates_to_injected_adapter(repo: Path) -> None:
    class FakeAdapter:
        name = "fake"

        def detect(self, repo_dir: Path) -> bool:
            return True

        def install(self, repo_dir: Path, *, runner: object = None) -> None:
            return None

        def test_command(self, repo_dir: Path) -> list[str]:
            return ["pytest"]

        def run_tests(self, repo_dir: Path, *, runner: object = None) -> TestResult:
            return TestResult(passed=True, output_tail="3 passed")

        def coverage(self, repo_dir: Path, *, runner: object = None) -> float | None:
            return 90.0

    result = dispatch(_call("run_tests"), _ctx(repo, adapter=FakeAdapter()))
    assert result.ok is True
    assert "passed" in result.content
    assert "3 passed" in result.content


def test_run_tests_without_adapter_returns_error(repo: Path) -> None:
    result = dispatch(_call("run_tests"), _ctx(repo))
    assert result.ok is False


def test_ripgrep_uses_injected_runner(repo: Path) -> None:
    calls: list[list[str]] = []

    def runner(argv: Sequence[str], **_kw: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return subprocess.CompletedProcess(
            args=list(argv), returncode=0, stdout="src.py:1:print('hello')\n", stderr=""
        )

    result = dispatch(_call("ripgrep_search", pattern="hello"), _ctx(repo, runner=runner))
    assert result.ok is True
    assert "src.py" in result.content
    assert calls and calls[0][0] == "rg"


def test_ripgrep_missing_rg_falls_back_gracefully(repo: Path) -> None:
    def runner(argv: Sequence[str], **_kw: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("rg")

    result = dispatch(_call("ripgrep_search", pattern="x"), _ctx(repo, runner=runner))
    assert result.ok is False
    assert "ripgrep" in result.content


def test_repo_map_lists_files(repo: Path) -> None:
    result = dispatch(_call("repo_map"), _ctx(repo))
    assert result.ok is True
    assert "src.py" in result.content


def test_finish_returns_summary(repo: Path) -> None:
    result = dispatch(_call("finish", summary="done fixing"), _ctx(repo))
    assert result.ok is True
    assert result.content == "done fixing"


def test_unknown_tool_returns_error(repo: Path) -> None:
    result = dispatch(_call("nonexistent"), _ctx(repo))
    assert result.ok is False
    assert "unknown tool" in result.content


def test_build_toolset_includes_finish_and_specs() -> None:
    specs = build_toolset()
    names = {s.name for s in specs}
    assert {"ripgrep_search", "repo_map", "read_file", "edit_file", "run_tests", "finish"} <= names
    for spec in specs:
        assert spec.parameters["type"] == "object"


# --- security regression tests (from worker security review) ----------------


def test_allowlist_rejects_git_dir_write_hook(repo: Path) -> None:
    # Writing .git/hooks/* is RCE on the next git op — must be blocked.
    result = dispatch(
        _call("apply_patch", path=".git/hooks/pre-commit", content="#!/bin/sh\nid\n"),
        _ctx(repo),
    )
    assert result.ok is False
    assert ".git" in result.content
    assert not (repo / ".git" / "hooks" / "pre-commit").exists()


def test_allowlist_rejects_git_config_write(repo: Path) -> None:
    result = dispatch(
        _call("edit_file", path=".git/config", old_str="x", new_str="y"),
        _ctx(repo),
    )
    assert result.ok is False
    assert not (repo / ".git" / "config").exists()


def test_allowlist_rejects_workflows_case_insensitive(repo: Path) -> None:
    # On case-insensitive FS, `.github/Workflows/` hits the same dir Actions reads.
    result = dispatch(
        _call("apply_patch", path=".github/Workflows/ci.yml", content="on: nothing\n"),
        _ctx(repo),
    )
    assert result.ok is False
    assert "workflows" in result.content.lower()


def test_ripgrep_argv_prevents_flag_injection(repo: Path) -> None:
    calls: list[list[str]] = []

    def runner(argv: Sequence[str], **_kw: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return subprocess.CompletedProcess(args=list(argv), returncode=1, stdout="", stderr="")

    # A pattern that would be a dangerous rg flag if passed positionally.
    dispatch(_call("ripgrep_search", pattern="--pre=/bin/sh"), _ctx(repo, runner=runner))
    argv = calls[0]
    assert "--no-config" in argv
    assert "--regexp" in argv
    assert "--" in argv
    # The pattern is bound to --regexp and the path sits after `--`, so the
    # malicious value can never be parsed as a ripgrep flag.
    assert argv[argv.index("--regexp") + 1] == "--pre=/bin/sh"
    assert argv.index("--") < argv.index(".")
