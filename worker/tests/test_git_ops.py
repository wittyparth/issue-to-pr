from __future__ import annotations

import base64
import subprocess
from collections.abc import Sequence
from pathlib import Path

from it2pr_worker.git_ops import checkout_new_branch, clone_repo


class _RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(args=list(argv), returncode=0, stdout="", stderr="")


def test_clone_repo_uses_header_auth_and_no_token_in_url() -> None:
    runner = _RecordingRunner()
    token = "ghs_supersecrettoken"  # noqa: S105

    clone_repo("octocat/hello-world", token, "/tmp/dest", runner=runner)

    assert len(runner.calls) == 1
    argv = runner.calls[0]

    assert argv[0] == "git"
    assert "clone" in argv

    # The token must appear (base64-encoded, Basic auth) in an
    # http.extraHeader config value...
    header_args = [a for a in argv if "extraHeader" in a]
    assert header_args, "expected an http.extraHeader argument"
    expected_basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    assert any(expected_basic in a for a in header_args)

    # ...and must NEVER appear in the URL argument.
    url_args = [a for a in argv if a.startswith("https://github.com/")]
    assert url_args == ["https://github.com/octocat/hello-world.git"]
    assert all(token not in a for a in url_args)

    assert argv[-1] == "/tmp/dest"


def test_clone_repo_argv_structure() -> None:
    runner = _RecordingRunner()

    clone_repo("owner/repo", "tok", Path("/tmp/dest2"), runner=runner)

    argv = runner.calls[0]
    expected_basic = base64.b64encode(b"x-access-token:tok").decode()
    assert argv == [
        "git",
        "-c",
        f"http.extraHeader=Authorization: Basic {expected_basic}",
        "-c",
        "core.hooksPath=",
        "clone",
        "https://github.com/owner/repo.git",
        "/tmp/dest2",
    ]


def test_checkout_new_branch_argv() -> None:
    runner = _RecordingRunner()

    checkout_new_branch("/tmp/dest", "agent/issue-42-abc123", runner=runner)

    assert runner.calls == [
        [
            "git",
            "-C",
            "/tmp/dest",
            "-c",
            "core.hooksPath=",
            "checkout",
            "-b",
            "agent/issue-42-abc123",
        ]
    ]
