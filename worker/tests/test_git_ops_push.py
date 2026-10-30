from __future__ import annotations

import base64
import subprocess
from collections.abc import Sequence

from it2pr_worker.git_ops import push_branch


class _RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(args=list(argv), returncode=0, stdout="", stderr="")


def test_push_branch_is_non_force_and_uses_header_auth() -> None:
    runner = _RecordingRunner()
    token = "ghs_supersecrettoken"  # noqa: S105

    push_branch("/tmp/repo", "agent/issue-1-abc", token, runner=runner)

    assert len(runner.calls) == 1
    argv = runner.calls[0]

    assert argv[0] == "git"
    assert "push" in argv

    # Non-force: no --force/-f flag anywhere, and no +refspec force-push form.
    assert "--force" not in argv
    assert "-f" not in argv
    assert not any(a.startswith("+") for a in argv)

    # Token via header (base64-encoded Basic auth), never in a URL argument.
    header_args = [a for a in argv if "extraHeader" in a]
    assert header_args
    expected_basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    assert any(expected_basic in a for a in header_args)
    assert not any(a.startswith("https://") and token in a for a in argv)

    assert argv[-2:] == ["origin", "agent/issue-1-abc"]


def test_push_branch_disables_core_hooks_path() -> None:
    runner = _RecordingRunner()

    push_branch("/tmp/repo", "agent/issue-2", "tok", runner=runner)

    argv = runner.calls[0]
    assert "core.hooksPath=" in argv


def test_clone_and_checkout_also_disable_core_hooks_path() -> None:
    from it2pr_worker.git_ops import checkout_new_branch, clone_repo

    clone_runner = _RecordingRunner()
    clone_repo("owner/repo", "tok", "/tmp/dest", runner=clone_runner)
    assert "core.hooksPath=" in clone_runner.calls[0]

    checkout_runner = _RecordingRunner()
    checkout_new_branch("/tmp/dest", "agent/issue-3", runner=checkout_runner)
    assert "core.hooksPath=" in checkout_runner.calls[0]
