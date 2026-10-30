"""Git operations for the worker sandbox.

CRITICAL security requirement (Principle 1 + pre-mortem #2): the installation
token MUST be passed via an HTTP extra-header, NEVER embedded in the remote
URL. A token in the URL lands in `.git/config` and the reflog, defeating
secret hygiene. `runner` is injectable so tests assert the argv without
running real git and can confirm the token is absent from the URL argument.
"""

from __future__ import annotations

import base64
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

RunnerResult = subprocess.CompletedProcess[str]
Runner = Callable[[Sequence[str]], RunnerResult]


class GitOpsError(RuntimeError):
    """Raised when a git operation fails."""


def default_runner(argv: Sequence[str]) -> RunnerResult:
    return subprocess.run(  # noqa: S603
        list(argv),
        check=True,
        capture_output=True,
        text=True,
    )


def _auth_header_value(token: str) -> str:
    # Git's smart-HTTP endpoint (unlike the REST API) rejects `Bearer` and
    # requires HTTP Basic auth with the literal username `x-access-token`
    # and the installation token as the password.
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return f"Authorization: Basic {basic}"


def clone_repo(
    repo_full_name: str,
    token: str,
    dest_dir: Path | str,
    *,
    runner: Runner = default_runner,
) -> None:
    """Clone `repo_full_name` into `dest_dir`, authenticating via extra-header.

    The token never appears in the URL argument, so it cannot land in
    `.git/config` or the reflog.
    """
    url = f"https://github.com/{repo_full_name}.git"
    argv = [
        "git",
        "-c",
        f"http.extraHeader={_auth_header_value(token)}",
        "-c",
        "core.hooksPath=",
        "clone",
        url,
        str(dest_dir),
    ]
    try:
        runner(argv)
    except subprocess.CalledProcessError as exc:
        raise GitOpsError(f"git clone failed for {repo_full_name}") from exc


def checkout_new_branch(
    dest_dir: Path | str,
    branch: str,
    *,
    runner: Runner = default_runner,
) -> None:
    """Create and check out a new branch inside `dest_dir`."""
    argv = [
        "git",
        "-C",
        str(dest_dir),
        "-c",
        "core.hooksPath=",
        "checkout",
        "-b",
        branch,
    ]
    try:
        runner(argv)
    except subprocess.CalledProcessError as exc:
        raise GitOpsError(f"git checkout -b {branch} failed") from exc


def push_branch(
    repo_dir: Path | str,
    branch: str,
    token: str,
    *,
    runner: Runner = default_runner,
) -> None:
    """Push `branch` to `origin` via header auth, never force.

    Deliberately omits `--force`/`-f` and any `+refspec` force-push form:
    the worker must never be able to overwrite history on a protected
    branch. `-c core.hooksPath=` disables any repo-local hooks as
    defense-in-depth against a hook the agent may have written.
    """
    argv = [
        "git",
        "-C",
        str(repo_dir),
        "-c",
        f"http.extraHeader={_auth_header_value(token)}",
        "-c",
        "core.hooksPath=",
        "push",
        "origin",
        branch,
    ]
    try:
        runner(argv)
    except subprocess.CalledProcessError as exc:
        raise GitOpsError(f"git push origin {branch} failed") from exc


def clean_untracked(
    repo_dir: Path | str,
    *,
    keep: Sequence[str] = (".venv", "node_modules"),
    include_ignored: bool = False,
    runner: Runner = default_runner,
) -> None:
    """Remove untracked files/dirs (coverage artifacts, __pycache__, etc).

    `get_base_coverage` runs a real test+coverage pass at the base commit
    before the agent branch is cut, and the agent's own `run_tests` tool
    triggers further pytest/bytecode-compile runs during the loop; both leave
    untracked files (`.coverage`, `htmlcov/`, `.pytest_cache/`, `__pycache__/`,
    `*.pyc`) sitting in the working tree. Those would otherwise ride along
    into the PR commit via `commit_all`'s `git add -A`. `keep` excludes
    installed dependency directories so a prior `adapter.install()` isn't
    undone. `include_ignored` also sweeps files matched by the repo's own
    `.gitignore` (e.g. `__pycache__` when the repo doesn't ignore it itself)
    -- pass True right before the final commit, once the agent is done
    running tests.
    """
    argv = ["git", "-C", str(repo_dir), "clean", "-fdx" if include_ignored else "-fd"]
    for path in keep:
        argv.extend(["-e", path])
    try:
        runner(argv)
    except subprocess.CalledProcessError as exc:
        raise GitOpsError("git clean failed") from exc


def commit_all(
    repo_dir: Path | str,
    message: str,
    *,
    runner: Runner = default_runner,
) -> bool:
    """Stage and commit all working-tree changes in `repo_dir`.

    The agent's edit/write tools only touch the filesystem; nothing else in
    the pipeline turns those edits into a real commit, and `push_branch` can
    only push committed history. Returns False (no-op) when the tree is
    clean, so callers can distinguish "agent made no changes" from a real
    commit.
    """
    status = runner(["git", "-C", str(repo_dir), "status", "--porcelain"])
    if not status.stdout.strip():
        return False
    try:
        runner(["git", "-C", str(repo_dir), "add", "-A"])
        runner(
            [
                "git",
                "-C",
                str(repo_dir),
                "-c",
                "user.name=it2pr-agent",
                "-c",
                "user.email=it2pr-agent@users.noreply.github.com",
                "commit",
                "-m",
                message,
            ]
        )
    except subprocess.CalledProcessError as exc:
        raise GitOpsError("git commit failed") from exc
    return True


def current_branch(
    repo_dir: Path | str,
    *,
    runner: Runner = default_runner,
) -> str:
    """Return the currently checked-out branch name (`git rev-parse --abbrev-ref HEAD`)."""
    argv = ["git", "-C", str(repo_dir), "rev-parse", "--abbrev-ref", "HEAD"]
    try:
        result = runner(argv)
    except subprocess.CalledProcessError as exc:
        raise GitOpsError("git rev-parse --abbrev-ref HEAD failed") from exc
    return result.stdout.strip()


def head_sha(
    repo_dir: Path | str,
    *,
    runner: Runner = default_runner,
) -> str:
    """Return the current HEAD commit SHA (`git rev-parse HEAD`)."""
    argv = ["git", "-C", str(repo_dir), "rev-parse", "HEAD"]
    try:
        result = runner(argv)
    except subprocess.CalledProcessError as exc:
        raise GitOpsError("git rev-parse HEAD failed") from exc
    return result.stdout.strip()


def diff_summary(
    repo_dir: Path | str,
    base: str,
    *,
    runner: Runner = default_runner,
) -> str:
    """Return a `git diff --stat` summary of changes against `base`."""
    argv = ["git", "-C", str(repo_dir), "diff", "--stat", base]
    try:
        result = runner(argv)
    except subprocess.CalledProcessError as exc:
        raise GitOpsError(f"git diff --stat {base} failed") from exc
    return result.stdout


def changed_files(
    repo_dir: Path | str,
    base: str,
    *,
    runner: Runner = default_runner,
) -> list[str]:
    """Return the list of file paths changed relative to `base`."""
    argv = ["git", "-C", str(repo_dir), "diff", "--name-only", base]
    try:
        result = runner(argv)
    except subprocess.CalledProcessError as exc:
        raise GitOpsError(f"git diff --name-only {base} failed") from exc
    return [line for line in result.stdout.splitlines() if line]
