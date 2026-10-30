"""Worker entrypoint.

M3 wires the run-config load, token mint, clone, checkout, and adapter
selection/install/test slice. The heavy I/O (real network calls, real git,
real installs/tests) only happens under the `if __name__ == "__main__"` path;
`run()` accepts injected dependencies so it can be exercised without any of
that in unit tests.
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from it2pr_worker import __version__
from it2pr_worker.adapters.base import CoverageToolAbsentError, InferenceFailure, LanguageAdapter
from it2pr_worker.adapters.registry import select_adapter
from it2pr_worker.agent import LimitTracker, ToolContext, run_agent
from it2pr_worker.config import RunConfig
from it2pr_worker.coverage_base import get_base_coverage
from it2pr_worker.git_ops import (
    Runner,
    checkout_new_branch,
    clean_untracked,
    clone_repo,
    commit_all,
    current_branch,
    diff_summary,
    head_sha,
)
from it2pr_worker.git_ops import default_runner as default_git_runner
from it2pr_worker.github_api import GitHubClient
from it2pr_worker.llm.base import Provider
from it2pr_worker.llm.factory import build_provider
from it2pr_worker.logging_setup import install_scrubbing_logging
from it2pr_worker.observability import Tracer, build_tracer
from it2pr_worker.post_result import post_result
from it2pr_worker.scrub import scrub
from it2pr_worker.secrets import (
    GithubAppCreds,
    SecretsError,
    fetch_github_app_credentials,
    fetch_llm_provider_keys,
)
from it2pr_worker.token import InstallationToken, get_installation_token
from it2pr_worker.verify import verify_and_gate

logger = logging.getLogger(__name__)


def run(
    config: RunConfig,
    dest_dir: Path,
    *,
    app_id: str,
    private_key_pem: str,
    mint_token: Callable[..., InstallationToken] = get_installation_token,
    git_runner: Runner = default_git_runner,
    tracer: Tracer | None = None,
    provider_factory: Callable[[], Provider] = build_provider,
    github_client_factory: Callable[[str], GitHubClient] = GitHubClient,
    select_adapter: Callable[[Path], LanguageAdapter | InferenceFailure] = select_adapter,
) -> int:
    """Run the full issue-to-PR pipeline for one issue.

    Clone the repo, capture its base branch/commit, measure base coverage,
    check out the agent branch, install deps, fetch the issue text, run the
    LLM fix loop, verify the resulting tree, and post the result (comment or
    PR). Returns a process-style exit code (0 on success, non-zero if the
    environment could not be inferred).
    """
    installation_token = mint_token(config.installation_id, app_id, private_key_pem)
    github_client = github_client_factory(installation_token.token)

    try:
        clone_repo(config.repo_full_name, installation_token.token, dest_dir, runner=git_runner)

        # Capture the repo's default branch/commit at clone time (before we
        # create the agent branch), so we have a base to diff and measure
        # coverage against.
        base_branch = current_branch(dest_dir, runner=git_runner)
        base_sha = head_sha(dest_dir, runner=git_runner)

        adapter_or_failure = select_adapter(dest_dir)
        if isinstance(adapter_or_failure, InferenceFailure):
            print(
                f"it2pr-worker: environment inference failed: {adapter_or_failure.reason.value}"
            )
            return 1
        adapter: LanguageAdapter = adapter_or_failure

        # Install deps BEFORE measuring base coverage: coverage/pytest need the
        # project's own dependencies importable, and this runs at base_sha
        # (HEAD right after clone), so the installed environment is valid for
        # both the base-coverage run and the agent branch cut from the same
        # commit below.
        adapter.install(dest_dir)

        try:
            base_coverage = get_base_coverage(dest_dir, base_sha, adapter, git_runner=git_runner)
        except CoverageToolAbsentError:
            base_coverage = None

        # get_base_coverage's test+coverage run leaves untracked artifacts
        # (.coverage, htmlcov/, .pytest_cache/) in the tree; clean them before
        # cutting the agent branch so they don't ride along into the PR commit.
        clean_untracked(dest_dir, runner=git_runner)
        checkout_new_branch(dest_dir, config.branch, runner=git_runner)

        issue = github_client.get_issue(config.repo_full_name, config.issue_number)

        provider = provider_factory()
        agent_result = run_agent(
            provider,
            ToolContext(repo_dir=dest_dir, adapter=adapter),
            issue_title=issue.title,
            issue_body=issue.body,
            limits=LimitTracker(),
            tracer=tracer,
        )

        # The agent's own run_tests tool calls during the loop can leave
        # bytecode-cache junk (__pycache__, *.pyc) in the tree; sweep it,
        # including gitignored matches, before it gets committed.
        clean_untracked(dest_dir, include_ignored=True, runner=git_runner)

        committed = commit_all(
            dest_dir, f"Fix issue #{config.issue_number}: {issue.title}", runner=git_runner
        )
        if not committed:
            github_client.create_issue_comment(
                config.repo_full_name,
                config.issue_number,
                "The agent finished without making any file changes, so no pull "
                f"request was opened.\n\n- Agent status: {agent_result.status}\n"
                f"- Agent summary: {agent_result.summary}\n",
            )
            print(f"it2pr-worker: adapter={adapter.name} agent={agent_result.status} outcome=no_changes")
            return 1

        verify_result = verify_and_gate(dest_dir, adapter, base_coverage)
        if not verify_result.tests_passed:
            print(
                f"it2pr-worker: test run failed, output tail:\n"
                f"{scrub(verify_result.test_output_tail)}"
            )

        diff_summary_text = diff_summary(dest_dir, base_sha, runner=git_runner)
        # run_agent opens and ends its own trace internally, so no per-run
        # trace id is exposed here; the tracer's trace_url() requires one.
        # Pass empty rather than fabricate a URL.

        outcome = post_result(
            repo_dir=dest_dir,
            repo_full_name=config.repo_full_name,
            issue_number=config.issue_number,
            base_branch=base_branch,
            branch=config.branch,
            agent_result=agent_result,
            verify_result=verify_result,
            installation_token=installation_token,
            trace_url="",
            github_client=github_client,
            token_provider=lambda: mint_token(config.installation_id, app_id, private_key_pem),
            now=lambda: datetime.now(UTC),
            git_runner=git_runner,
            diff_summary_text=diff_summary_text,
            github_client_factory=github_client_factory,
        )

        print(
            f"it2pr-worker: adapter={adapter.name} agent={agent_result.status} "
            f"decision={verify_result.decision} outcome={outcome.kind}"
        )
        return 0 if verify_result.tests_passed else 1
    except Exception as exc:  # noqa: BLE001 - last-resort: still tell the user something broke
        failure_comment = (
            "The automated run hit an unexpected error before verification could "
            f"complete, so no pull request was opened.\n\n```\n{scrub(str(exc))}\n```"
        )
        try:
            github_client.create_issue_comment(
                config.repo_full_name, config.issue_number, failure_comment
            )
        except Exception:  # noqa: BLE001 - the run already failed; don't mask it
            pass
        raise


def resolve_github_app_credentials(
    env: dict[str, str] | None = None,
    *,
    fetch_creds: Callable[..., GithubAppCreds] = fetch_github_app_credentials,
) -> GithubAppCreds | None:
    """Resolve GitHub App credentials for this run.

    Contract: prefer `GITHUB_APP_PARAM_NAME` (SSM Parameter Store, production
    path — the dispatcher injects only the parameter name, never the value).
    Falls back to the direct `GITHUB_APP_ID`/`GITHUB_APP_PRIVATE_KEY` env vars
    for local dev. Returns `None` if neither source is available. Never logs
    the resolved credentials.
    """
    source = env if env is not None else os.environ

    param_name = source.get("GITHUB_APP_PARAM_NAME")
    if param_name:
        try:
            creds = fetch_creds(param_name)
        except SecretsError as exc:
            logger.error("failed to resolve GitHub App credentials: %s", exc)
            return None
        return creds

    app_id = source.get("GITHUB_APP_ID")
    private_key_pem = source.get("GITHUB_APP_PRIVATE_KEY")
    if app_id and private_key_pem:
        return GithubAppCreds(app_id=app_id, private_key_pem=private_key_pem)

    return None


def resolve_llm_provider_keys(
    env: dict[str, str] | None = None,
    *,
    fetch_keys: Callable[..., dict[str, str]] = fetch_llm_provider_keys,
) -> dict[str, str]:
    """Fetch LLM provider keys from SSM Parameter Store, if configured.

    Contract: only acts when `LLM_PROVIDERS_PARAM_NAME` is set (the
    dispatcher injects the parameter name, never the value — see
    `app/src/lib/ecs.ts`). Returns an empty dict for local dev where the
    provider keys are already present directly in the environment. Never
    logs the resolved values.
    """
    source = env if env is not None else os.environ

    param_name = source.get("LLM_PROVIDERS_PARAM_NAME")
    if not param_name:
        return {}

    try:
        return fetch_keys(param_name)
    except SecretsError as exc:
        logger.error("failed to resolve LLM provider keys: %s", exc)
        return {}


def apply_llm_provider_keys(keys: dict[str, str], *, env: dict[str, str] | None = None) -> None:
    """Set fetched provider keys into the environment without clobbering pre-set vars."""
    target = env if env is not None else os.environ
    for name, value in keys.items():
        if name not in target:
            target[name] = value


def main(argv: list[str] | None = None) -> int:
    _ = argv if argv is not None else sys.argv[1:]

    install_scrubbing_logging()
    tracer = build_tracer()  # constructed here so a bad Langfuse config never blocks the run

    # Resolve LLM provider keys from SSM Parameter Store before any provider/
    # factory use (llm/factory.build_provider reads them from os.environ).
    apply_llm_provider_keys(resolve_llm_provider_keys())

    try:
        config = RunConfig.from_env()
    except Exception as exc:  # noqa: BLE001 - surface config errors, not a stack trace
        print(f"it2pr-worker {__version__}: config error: {exc}")
        return 0

    print(
        f"it2pr-worker {__version__}: loaded run config for "
        f"{config.repo_full_name}#{config.issue_number} (run={config.run_id})"
    )

    if os.environ.get("IT2PR_WORKER_SKIP_RUN"):
        return 0

    creds = resolve_github_app_credentials()
    if creds is None:
        print(
            "it2pr-worker: missing GitHub App credentials "
            "(set GITHUB_APP_PARAM_NAME or GITHUB_APP_ID/GITHUB_APP_PRIVATE_KEY); skipping run"
        )
        return 0

    dest_dir = Path(f"/tmp/it2pr-worker/{config.run_id}")  # noqa: S108
    try:
        return run(
            config,
            dest_dir,
            app_id=creds.app_id,
            private_key_pem=creds.private_key_pem,
            tracer=tracer,
        )
    except Exception:  # noqa: BLE001 - last line of defense before the default
        # excepthook would print the raw traceback (which can carry a live
        # installation token, e.g. inside a CalledProcessError's argv) to
        # stderr/CloudWatch, entirely bypassing install_scrubbing_logging()
        # (that only patches the `logging` module, not sys.excepthook).
        print(scrub(traceback.format_exc()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
