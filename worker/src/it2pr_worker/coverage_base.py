"""Base-commit coverage strategy (M5, MAJOR-2 / pre-mortem #7).

Coverage delta is measured against a *base* commit's coverage. Recomputing
that on every run would double the wall-clock cost of an already-tight
30-minute budget, so an injectable SHA-keyed `cache` (e.g. backed by S3/
DynamoDB in production) lets a repeat run for the same base commit skip the
second full test run entirely.

Execution note (plan M5): on a cache miss the 30-minute wall-clock budget
must accommodate a full extra test run (checkout base + run coverage) on top
of the fix loop's own budget; callers should account for this separately
rather than let it starve fix time.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol

from it2pr_worker.adapters.base import LanguageAdapter, Runner
from it2pr_worker.adapters.base import default_runner as _default_runner
from it2pr_worker.git_ops import GitOpsError
from it2pr_worker.git_ops import Runner as GitRunner
from it2pr_worker.git_ops import default_runner as _default_git_runner


class CoverageCache(Protocol):
    def get(self, base_sha: str) -> float | None: ...

    def set(self, base_sha: str, coverage: float | None) -> None: ...


def get_base_coverage(
    repo_dir: Path,
    base_sha: str,
    adapter: LanguageAdapter,
    *,
    cache: CoverageCache | None = None,
    runner: Runner = _default_runner,
    git_runner: GitRunner = _default_git_runner,
) -> float | None:
    """Return the base commit's coverage percentage, using `cache` when possible.

    On a cache hit, returns the cached value without running any tests. On a
    miss, checks out `base_sha`, runs the adapter's coverage measurement,
    stores the result in `cache` (if provided), and returns it.
    """
    if cache is not None:
        cached = cache.get(base_sha)
        if cached is not None:
            return cached

    checkout_new_branch_or_sha(repo_dir, base_sha, runner=git_runner)
    coverage = adapter.coverage(repo_dir, runner=runner)

    if cache is not None:
        cache.set(base_sha, coverage)

    return coverage


def checkout_new_branch_or_sha(
    repo_dir: Path,
    ref: str,
    *,
    runner: GitRunner = _default_git_runner,
) -> None:
    """Check out `ref` (a commit SHA or branch name) in `repo_dir`.

    Uses plain `git checkout <ref>` (detached HEAD for a SHA) rather than
    `checkout_new_branch`, which always creates a new branch.
    """
    argv = ["git", "-C", str(repo_dir), "checkout", ref]
    try:
        runner(argv)
    except subprocess.CalledProcessError as exc:
        raise GitOpsError(f"git checkout {ref} failed") from exc
