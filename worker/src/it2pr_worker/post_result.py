"""Post-verification orchestration (M5): comment, push, PR, label, or reconcile.

Given an `AgentResult` + `VerifyResult`, decides the final GitHub action:

- `comment_only`: post an issue comment with a failure summary; no PR.
- `open_pr` / `open_pr_needs_review`: re-mint the installation token if it is
  near expiry, then push the branch and open a PR (or attach the
  `needs-review` label). Idempotent: if the branch already exists on origin
  and an open PR already exists for it, reconcile by returning the existing
  PR rather than re-pushing or re-creating (handles a retry after a prior
  run's push succeeded but PR-creation failed, MAJOR-6).

All GitHub/git/clock access is injected so this module is fully hermetic in
tests.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from it2pr_worker.agent import AgentResult
from it2pr_worker.git_ops import Runner as GitRunner
from it2pr_worker.git_ops import default_runner as _default_git_runner
from it2pr_worker.git_ops import push_branch
from it2pr_worker.github_api import GitHubClient, PullRequest
from it2pr_worker.pr_body import build_pr_body
from it2pr_worker.token import InstallationToken, needs_remint
from it2pr_worker.verify import VerifyResult

NEEDS_REVIEW_LABEL = "needs-review"

OutcomeKind = Literal["comment_only", "pr_opened", "pr_reconciled"]


@dataclass(frozen=True, slots=True)
class PostOutcome:
    kind: OutcomeKind
    pr: PullRequest | None = None
    comment_body: str | None = None
    labels_added: list[str] | None = None


def _build_failure_comment(agent_result: AgentResult, verify_result: VerifyResult) -> str:
    return (
        "The automated fix attempt did not pass verification, so no pull "
        "request was opened.\n\n"
        f"- Agent status: {agent_result.status}\n"
        f"- Agent summary: {agent_result.summary}\n"
        f"- Tests passed: {verify_result.tests_passed}\n"
    )


def post_result(
    *,
    repo_dir: Path,
    repo_full_name: str,
    issue_number: int,
    base_branch: str,
    branch: str,
    agent_result: AgentResult,
    verify_result: VerifyResult,
    installation_token: InstallationToken,
    trace_url: str,
    github_client: GitHubClient | None = None,
    token_provider: Callable[[], InstallationToken] | None = None,
    now: Callable[[], datetime] | None = None,
    git_runner: GitRunner = _default_git_runner,
    diff_summary_text: str = "",
    github_client_factory: Callable[[str], GitHubClient] = GitHubClient,
) -> PostOutcome:
    """Decide and execute the final GitHub action for this run.

    `github_client` should be constructed by the caller with the current
    token; if a re-mint occurs, this function builds a fresh client from the
    re-minted token via `github_client_factory(new_token.token)` (defaults to
    `GitHubClient`; tests inject a factory returning a fake client so no real
    network call is made).
    """
    if verify_result.decision == "comment_only":
        assert github_client is not None
        comment_body = _build_failure_comment(agent_result, verify_result)
        github_client.create_issue_comment(repo_full_name, issue_number, comment_body)
        return PostOutcome(kind="comment_only", comment_body=comment_body)

    token = installation_token
    if token_provider is not None and now is not None and needs_remint(token, now()):
        token = token_provider()
        github_client = github_client_factory(token.token)

    assert github_client is not None

    existing_branch = github_client.get_branch(repo_full_name, branch)
    existing_pr = github_client.get_open_pr(repo_full_name, branch) if existing_branch else None

    if existing_branch is not None and existing_pr is not None:
        # Idempotent recovery: a prior attempt already pushed and opened the
        # PR (or this is a genuine retry after a partial failure). Do not
        # re-push or re-create; just reconcile the label if needed.
        labels_added = None
        if verify_result.decision == "open_pr_needs_review":
            github_client.add_labels(repo_full_name, issue_number, [NEEDS_REVIEW_LABEL])
            labels_added = [NEEDS_REVIEW_LABEL]
        return PostOutcome(kind="pr_reconciled", pr=existing_pr, labels_added=labels_added)

    # Reaching here means NOT (branch exists AND pr exists) — the only case
    # that skips push is the true idempotent-recovery case handled above. Push
    # so the (possibly stale) remote branch reflects the current commits before
    # a PR is opened against it.
    push_branch(repo_dir, branch, token.token, runner=git_runner)

    pr_body = build_pr_body(
        rationale=agent_result.summary,
        diff_summary=diff_summary_text,
        coverage_delta=verify_result.coverage_delta,
        cost_usd=agent_result.cost_usd,
        turns=agent_result.turns,
        trace_url=trace_url,
        extra_secrets=[token.token],
    )

    pr = existing_pr
    if pr is None:
        pr = github_client.create_pull(
            repo_full_name,
            branch,
            base_branch,
            title=f"Fix issue #{issue_number}",
            body=pr_body,
        )

    labels_added = None
    if verify_result.decision == "open_pr_needs_review":
        github_client.add_labels(repo_full_name, issue_number, [NEEDS_REVIEW_LABEL])
        labels_added = [NEEDS_REVIEW_LABEL]

    return PostOutcome(kind="pr_opened", pr=pr, labels_added=labels_added)
