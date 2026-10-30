from __future__ import annotations

import logging
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from it2pr_worker.__main__ import apply_llm_provider_keys, resolve_llm_provider_keys, run
from it2pr_worker.adapters.base import InferenceFailure, InferenceFailureReason, TestResult
from it2pr_worker.config import RunConfig
from it2pr_worker.github_api import Issue, PullRequest
from it2pr_worker.llm.base import LLMResponse, ToolCall, Usage
from it2pr_worker.secrets import SecretsError
from it2pr_worker.token import InstallationToken


def _config() -> RunConfig:
    return RunConfig(
        repo_full_name="o/r",
        issue_number=42,
        installation_id=99,
        run_id="run-1",
        branch="agent/issue-42",
        event_kind="issue",
    )


def _ok(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(list(argv), 0, stdout="", stderr="")


class _FakeGitRunner:
    """Records argv and answers git read commands used by run()."""

    def __init__(self, *, dirty: bool = True) -> None:
        self.argv: list[list[str]] = []
        self._dirty = dirty

    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        args = list(argv)
        self.argv.append(args)
        if args[-3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return subprocess.CompletedProcess(args, 0, stdout="main\n", stderr="")
        if args[-2:] == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args, 0, stdout="basecommitsha\n", stderr="")
        if args[-2:] == ["status", "--porcelain"]:
            stdout = " M calc.py\n" if self._dirty else ""
            return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")
        if "diff" in args:
            return subprocess.CompletedProcess(args, 0, stdout=" 1 file changed\n", stderr="")
        return _ok(args)


class _FakeAdapter:
    name = "python"

    def __init__(self, *, tests_passed: bool = True, head_cov: float = 90.0) -> None:
        self._tests_passed = tests_passed
        self._head_cov = head_cov

    def detect(self, repo_dir: Path) -> bool:
        return True

    def install(self, repo_dir: Path, *, runner=None) -> None:
        return None

    def test_command(self, repo_dir: Path) -> list[str]:
        return ["pytest"]

    def run_tests(self, repo_dir: Path, *, runner=None) -> TestResult:
        return TestResult(passed=self._tests_passed, output_tail="")

    def coverage(self, repo_dir: Path, *, runner=None) -> float | None:
        return self._head_cov


class _FakeProvider:
    name = "fake"
    model = "fake-model"

    def complete(self, messages, tools=None) -> LLMResponse:
        return LLMResponse(
            content="done",
            tool_calls=[ToolCall(id="c1", name="finish", arguments={"summary": "fixed it"})],
            usage=Usage(prompt_tokens=1, completion_tokens=1, cost_usd=0.01),
        )


class _FakeGitHubClient:
    def __init__(self, token: str) -> None:
        self.token = token
        self.issue_comments: list[str] = []
        self.created_pull: PullRequest | None = None

    def get_issue(self, repo: str, issue: int) -> Issue:
        return Issue(number=issue, title="Broken thing", body="please fix")

    def get_branch(self, repo: str, branch: str):
        return None

    def get_open_pr(self, repo: str, head: str):
        return None

    def create_pull(self, repo, head, base, title, body) -> PullRequest:
        self.created_pull = PullRequest(
            number=7, html_url="https://github.com/o/r/pull/7", state="open", head_ref=head
        )
        return self.created_pull

    def create_issue_comment(self, repo, issue, body) -> dict:
        self.issue_comments.append(body)
        return {"id": 1}

    def add_labels(self, repo, issue, labels) -> dict:
        return {}


def _token() -> InstallationToken:
    return InstallationToken(token="ghs_tok", expires_at=datetime.now(UTC) + timedelta(hours=1))


def _mint(installation_id, app_id, private_key_pem, **kwargs) -> InstallationToken:
    return _token()


def test_resolve_returns_empty_when_secret_arn_not_set() -> None:
    keys = resolve_llm_provider_keys({})

    assert keys == {}


def test_resolve_fetches_keys_via_injected_fetcher_when_param_name_set() -> None:
    calls: list[str] = []

    def fake_fetch(param_name: str) -> dict[str, str]:
        calls.append(param_name)
        return {"OPENROUTER_API_KEY": "or-key-123"}

    keys = resolve_llm_provider_keys(
        {"LLM_PROVIDERS_PARAM_NAME": "/it2pr/llm-providers"},
        fetch_keys=fake_fetch,
    )

    assert keys == {"OPENROUTER_API_KEY": "or-key-123"}
    assert calls == ["/it2pr/llm-providers"]


def test_resolve_returns_empty_and_logs_on_secrets_error(caplog: pytest.LogCaptureFixture) -> None:
    def failing_fetch(param_name: str) -> dict[str, str]:
        raise SecretsError(f"boom for {param_name!r}")

    with caplog.at_level(logging.ERROR):
        keys = resolve_llm_provider_keys(
            {"LLM_PROVIDERS_PARAM_NAME": "/it2pr/llm-providers"},
            fetch_keys=failing_fetch,
        )

    assert keys == {}
    assert "failed to resolve LLM provider keys" in caplog.text


def test_apply_sets_keys_into_target_env() -> None:
    env: dict[str, str] = {}

    apply_llm_provider_keys({"OPENROUTER_API_KEY": "or-key-123"}, env=env)

    assert env == {"OPENROUTER_API_KEY": "or-key-123"}


def test_apply_never_clobbers_pre_set_vars() -> None:
    env = {"OPENROUTER_API_KEY": "existing-local-dev-key"}

    apply_llm_provider_keys({"OPENROUTER_API_KEY": "fetched-key-should-not-win"}, env=env)

    assert env == {"OPENROUTER_API_KEY": "existing-local-dev-key"}


def test_apply_never_logs_key_values(caplog: pytest.LogCaptureFixture) -> None:
    env: dict[str, str] = {}

    with caplog.at_level(logging.DEBUG):
        apply_llm_provider_keys({"OPENROUTER_API_KEY": "super-secret-value"}, env=env)

    assert "super-secret-value" not in caplog.text


def test_run_full_pipeline_opens_pr_when_green(tmp_path: Path) -> None:
    git = _FakeGitRunner()
    client = _FakeGitHubClient("ghs_tok")

    exit_code = run(
        _config(),
        tmp_path,
        app_id="1",
        private_key_pem="pem",
        mint_token=_mint,
        git_runner=git,
        provider_factory=_FakeProvider,
        github_client_factory=lambda _tok: client,
        select_adapter=lambda _d: _FakeAdapter(tests_passed=True),
    )

    assert exit_code == 0
    assert client.created_pull is not None
    assert client.issue_comments == []
    # Base branch/commit were captured before the agent branch checkout.
    assert ["git", "-C", str(tmp_path), "rev-parse", "--abbrev-ref", "HEAD"] in git.argv
    # A push happened before opening the PR.
    assert any("push" in a for a in git.argv)


def test_run_comments_only_when_tests_red(tmp_path: Path) -> None:
    git = _FakeGitRunner()
    client = _FakeGitHubClient("ghs_tok")

    exit_code = run(
        _config(),
        tmp_path,
        app_id="1",
        private_key_pem="pem",
        mint_token=_mint,
        git_runner=git,
        provider_factory=_FakeProvider,
        github_client_factory=lambda _tok: client,
        select_adapter=lambda _d: _FakeAdapter(tests_passed=False),
    )

    assert exit_code == 1
    assert client.created_pull is None
    assert len(client.issue_comments) == 1


def test_run_comments_only_when_agent_makes_no_changes(tmp_path: Path) -> None:
    """A clean working tree after the agent loop must never reach push/create_pull.

    Regression guard for the exact bug class that already shipped once: an
    agent that finishes without editing anything produces a branch identical
    to base, and `create_pull` 422s ("no commits between") if the pipeline
    tries anyway.
    """
    git = _FakeGitRunner(dirty=False)
    client = _FakeGitHubClient("ghs_tok")

    exit_code = run(
        _config(),
        tmp_path,
        app_id="1",
        private_key_pem="pem",
        mint_token=_mint,
        git_runner=git,
        provider_factory=_FakeProvider,
        github_client_factory=lambda _tok: client,
        select_adapter=lambda _d: _FakeAdapter(tests_passed=True),
    )

    assert exit_code == 1
    assert client.created_pull is None
    assert len(client.issue_comments) == 1
    assert not any("push" in a for a in git.argv)


def test_run_returns_1_on_inference_failure(tmp_path: Path) -> None:
    git = _FakeGitRunner()
    client = _FakeGitHubClient("ghs_tok")
    failure = InferenceFailure(reason=InferenceFailureReason.UNSUPPORTED_REPO)

    exit_code = run(
        _config(),
        tmp_path,
        app_id="1",
        private_key_pem="pem",
        mint_token=_mint,
        git_runner=git,
        provider_factory=_FakeProvider,
        github_client_factory=lambda _tok: client,
        select_adapter=lambda _d: failure,
    )

    assert exit_code == 1
    assert client.created_pull is None
    assert client.issue_comments == []
