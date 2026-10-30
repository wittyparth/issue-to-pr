from __future__ import annotations

import base64
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from it2pr_worker.agent import AgentResult
from it2pr_worker.github_api import PullRequest
from it2pr_worker.post_result import NEEDS_REVIEW_LABEL, post_result
from it2pr_worker.token import InstallationToken
from it2pr_worker.verify import VerifyResult


class _RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(args=list(argv), returncode=0, stdout="", stderr="")


class _FakeGitHubClient:
    def __init__(
        self,
        *,
        existing_branch: dict | None = None,
        existing_pr: PullRequest | None = None,
    ) -> None:
        self.existing_branch = existing_branch
        self.existing_pr = existing_pr
        self.comments: list[tuple[str, int, str]] = []
        self.created_prs: list[tuple[str, str, str, str, str]] = []
        self.labels_added: list[tuple[str, int, list[str]]] = []

    def get_branch(self, repo: str, branch: str):
        return self.existing_branch

    def get_open_pr(self, repo: str, head: str):
        return self.existing_pr

    def create_issue_comment(self, repo: str, issue: int, body: str):
        self.comments.append((repo, issue, body))
        return {"id": 1}

    def create_pull(self, repo: str, head: str, base: str, title: str, body: str):
        self.created_prs.append((repo, head, base, title, body))
        return PullRequest(
            number=9, html_url="https://github.com/o/r/pull/9", state="open", head_ref=head
        )

    def add_labels(self, repo: str, issue: int, labels: list[str]):
        self.labels_added.append((repo, issue, labels))
        return {}


def _agent_result(status: str = "finished", summary: str = "did a fix") -> AgentResult:
    return AgentResult(status=status, turns=2, cost_usd=0.5, summary=summary, messages=[])


def _fresh_token(now: datetime) -> InstallationToken:
    return InstallationToken(token="ghs_current", expires_at=now + timedelta(hours=1))  # noqa: S106


def test_comment_only_path_posts_comment_and_no_pr() -> None:
    client = _FakeGitHubClient()
    verify_result = VerifyResult(
        tests_passed=False, head_coverage=None, coverage_delta=None, decision="comment_only"
    )
    now = datetime.now(UTC)

    outcome = post_result(
        repo_dir=Path("/tmp/repo"),
        repo_full_name="o/r",
        issue_number=5,
        base_branch="main",
        branch="agent/issue-5-abc",
        agent_result=_agent_result(status="limit_turns", summary="ran out of turns"),
        verify_result=verify_result,
        installation_token=_fresh_token(now),
        trace_url="https://trace",
        github_client=client,
    )

    assert outcome.kind == "comment_only"
    assert len(client.comments) == 1
    assert client.created_prs == []
    assert "ran out of turns" in outcome.comment_body


def test_open_pr_path_pushes_and_creates_pr() -> None:
    client = _FakeGitHubClient(existing_branch=None, existing_pr=None)
    runner = _RecordingRunner()
    verify_result = VerifyResult(
        tests_passed=True, head_coverage=90.0, coverage_delta=1.0, decision="open_pr"
    )
    now = datetime.now(UTC)

    outcome = post_result(
        repo_dir=Path("/tmp/repo"),
        repo_full_name="o/r",
        issue_number=5,
        base_branch="main",
        branch="agent/issue-5-abc",
        agent_result=_agent_result(),
        verify_result=verify_result,
        installation_token=_fresh_token(now),
        trace_url="https://trace",
        github_client=client,
        git_runner=runner,
        diff_summary_text="1 file changed",
    )

    assert outcome.kind == "pr_opened"
    assert outcome.pr is not None
    assert outcome.pr.number == 9
    assert len(client.created_prs) == 1
    assert len(runner.calls) == 1
    assert "push" in runner.calls[0]
    assert outcome.labels_added is None


def test_needs_review_adds_label() -> None:
    client = _FakeGitHubClient(existing_branch=None, existing_pr=None)
    runner = _RecordingRunner()
    verify_result = VerifyResult(
        tests_passed=True, head_coverage=70.0, coverage_delta=-10.0, decision="open_pr_needs_review"
    )
    now = datetime.now(UTC)

    outcome = post_result(
        repo_dir=Path("/tmp/repo"),
        repo_full_name="o/r",
        issue_number=5,
        base_branch="main",
        branch="agent/issue-5-abc",
        agent_result=_agent_result(),
        verify_result=verify_result,
        installation_token=_fresh_token(now),
        trace_url="https://trace",
        github_client=client,
        git_runner=runner,
    )

    assert outcome.kind == "pr_opened"
    assert outcome.labels_added == [NEEDS_REVIEW_LABEL]
    assert client.labels_added == [("o/r", 5, [NEEDS_REVIEW_LABEL])]


def test_idempotent_recovery_no_duplicate_create_when_branch_and_pr_exist() -> None:
    existing_pr = PullRequest(
        number=3,
        html_url="https://github.com/o/r/pull/3",
        state="open",
        head_ref="agent/issue-5-abc",
    )
    client = _FakeGitHubClient(
        existing_branch={"name": "agent/issue-5-abc"}, existing_pr=existing_pr
    )
    runner = _RecordingRunner()
    verify_result = VerifyResult(
        tests_passed=True, head_coverage=90.0, coverage_delta=1.0, decision="open_pr"
    )
    now = datetime.now(UTC)

    outcome = post_result(
        repo_dir=Path("/tmp/repo"),
        repo_full_name="o/r",
        issue_number=5,
        base_branch="main",
        branch="agent/issue-5-abc",
        agent_result=_agent_result(),
        verify_result=verify_result,
        installation_token=_fresh_token(now),
        trace_url="https://trace",
        github_client=client,
        git_runner=runner,
    )

    assert outcome.kind == "pr_reconciled"
    assert outcome.pr is existing_pr
    # no re-push, no duplicate create
    assert runner.calls == []
    assert client.created_prs == []


def test_existing_branch_without_open_pr_pushes_then_creates() -> None:
    # Remote branch exists but there is NO open PR (e.g. prior push landed,
    # PR-creation failed, and the branch is now stale). We must push the current
    # commits before opening the PR, not skip push and reflect stale commits.
    client = _FakeGitHubClient(
        existing_branch={"name": "agent/issue-5-abc"}, existing_pr=None
    )
    runner = _RecordingRunner()
    verify_result = VerifyResult(
        tests_passed=True, head_coverage=90.0, coverage_delta=1.0, decision="open_pr"
    )
    now = datetime.now(UTC)

    outcome = post_result(
        repo_dir=Path("/tmp/repo"),
        repo_full_name="o/r",
        issue_number=5,
        base_branch="main",
        branch="agent/issue-5-abc",
        agent_result=_agent_result(),
        verify_result=verify_result,
        installation_token=_fresh_token(now),
        trace_url="https://trace",
        github_client=client,
        git_runner=runner,
    )

    assert outcome.kind == "pr_opened"
    # push WAS called, then create_pull
    assert len(runner.calls) == 1
    assert "push" in runner.calls[0]
    assert len(client.created_prs) == 1


def test_idempotent_recovery_adds_label_when_needs_review() -> None:
    existing_pr = PullRequest(
        number=3,
        html_url="https://github.com/o/r/pull/3",
        state="open",
        head_ref="agent/issue-5-abc",
    )
    client = _FakeGitHubClient(
        existing_branch={"name": "agent/issue-5-abc"}, existing_pr=existing_pr
    )
    verify_result = VerifyResult(
        tests_passed=True, head_coverage=70.0, coverage_delta=-10.0, decision="open_pr_needs_review"
    )
    now = datetime.now(UTC)

    outcome = post_result(
        repo_dir=Path("/tmp/repo"),
        repo_full_name="o/r",
        issue_number=5,
        base_branch="main",
        branch="agent/issue-5-abc",
        agent_result=_agent_result(),
        verify_result=verify_result,
        installation_token=_fresh_token(now),
        trace_url="https://trace",
        github_client=client,
    )

    assert outcome.kind == "pr_reconciled"
    assert outcome.labels_added == [NEEDS_REVIEW_LABEL]


def test_token_remint_fires_when_near_expiry() -> None:
    now = datetime.now(UTC)
    near_expiry_token = InstallationToken(token="ghs_old", expires_at=now + timedelta(seconds=60))  # noqa: S106
    fresh_token = InstallationToken(token="ghs_new", expires_at=now + timedelta(hours=1))  # noqa: S106

    provider_calls = {"count": 0}

    def token_provider() -> InstallationToken:
        provider_calls["count"] += 1
        return fresh_token

    client = _FakeGitHubClient(existing_branch=None, existing_pr=None)
    runner = _RecordingRunner()
    verify_result = VerifyResult(
        tests_passed=True, head_coverage=90.0, coverage_delta=1.0, decision="open_pr"
    )

    outcome = post_result(
        repo_dir=Path("/tmp/repo"),
        repo_full_name="o/r",
        issue_number=5,
        base_branch="main",
        branch="agent/issue-5-abc",
        agent_result=_agent_result(),
        verify_result=verify_result,
        installation_token=near_expiry_token,
        trace_url="https://trace",
        github_client=client,
        token_provider=token_provider,
        now=lambda: now,
        git_runner=runner,
        github_client_factory=lambda _token: client,
    )

    assert provider_calls["count"] == 1
    assert outcome.kind == "pr_opened"
    # push was called with the re-minted token, not the near-expiry one
    # (auth header is base64-encoded Basic auth, see git_ops.py)
    push_argv = runner.calls[0]
    new_basic = base64.b64encode(b"x-access-token:ghs_new").decode()
    old_basic = base64.b64encode(b"x-access-token:ghs_old").decode()
    assert any(new_basic in a for a in push_argv)
    assert not any(old_basic in a for a in push_argv)


def test_token_remint_does_not_fire_when_fresh() -> None:
    now = datetime.now(UTC)
    fresh_token = InstallationToken(token="ghs_current", expires_at=now + timedelta(hours=1))  # noqa: S106

    provider_calls = {"count": 0}

    def token_provider() -> InstallationToken:
        provider_calls["count"] += 1
        return fresh_token

    client = _FakeGitHubClient(existing_branch=None, existing_pr=None)
    runner = _RecordingRunner()
    verify_result = VerifyResult(
        tests_passed=True, head_coverage=90.0, coverage_delta=1.0, decision="open_pr"
    )

    post_result(
        repo_dir=Path("/tmp/repo"),
        repo_full_name="o/r",
        issue_number=5,
        base_branch="main",
        branch="agent/issue-5-abc",
        agent_result=_agent_result(),
        verify_result=verify_result,
        installation_token=fresh_token,
        trace_url="https://trace",
        github_client=client,
        token_provider=token_provider,
        now=lambda: now,
        git_runner=runner,
    )

    assert provider_calls["count"] == 0
