import pytest

from it2pr_worker.config import ConfigError, RunConfig

VALID_ENV = {
    "REPO_FULL_NAME": "octocat/hello-world",
    "ISSUE_NUMBER": "42",
    "INSTALLATION_ID": "12345",
    "RUN_ID": "run-abc123",
    "BRANCH": "agent/issue-42-abc123",
    "EVENT_KIND": "issues.labeled",
}


def test_from_env_success() -> None:
    config = RunConfig.from_env(env=VALID_ENV)

    assert config.repo_full_name == "octocat/hello-world"
    assert config.issue_number == 42
    assert config.installation_id == 12345
    assert config.run_id == "run-abc123"
    assert config.branch == "agent/issue-42-abc123"
    assert config.event_kind == "issues.labeled"


@pytest.mark.parametrize("missing_key", list(VALID_ENV.keys()))
def test_from_env_missing_var_raises(missing_key: str) -> None:
    env = dict(VALID_ENV)
    del env[missing_key]

    with pytest.raises(ConfigError, match=missing_key):
        RunConfig.from_env(env=env)


def test_from_env_invalid_issue_number_raises() -> None:
    env = dict(VALID_ENV)
    env["ISSUE_NUMBER"] = "not-a-number"

    with pytest.raises(ConfigError):
        RunConfig.from_env(env=env)


def test_from_env_invalid_repo_full_name_raises() -> None:
    env = dict(VALID_ENV)
    env["REPO_FULL_NAME"] = "no-slash-here"

    with pytest.raises(ConfigError):
        RunConfig.from_env(env=env)
