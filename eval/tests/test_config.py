from __future__ import annotations

import json
from pathlib import Path

import pytest

from it2pr_eval.config import DEFAULT_CONFIG, ConfigError, EvalConfig, FixtureRepo


def test_default_config_is_valid_and_pinned() -> None:
    assert DEFAULT_CONFIG.temperature == 0.0
    assert DEFAULT_CONFIG.model
    assert DEFAULT_CONFIG.prompt_version
    assert DEFAULT_CONFIG.fixture_repos
    for repo in DEFAULT_CONFIG.fixture_repos:
        assert repo.commit_sha


def test_pass_rate_floor_present_and_defaults_to_eight() -> None:
    assert DEFAULT_CONFIG.pass_rate_floor == 8


def test_missing_commit_sha_raises() -> None:
    empty_sha_repo = FixtureRepo(full_name="org/repo", commit_sha="", language="python")
    with pytest.raises(ConfigError, match="commit_sha"):
        EvalConfig(
            model="m",
            temperature=0.0,
            prompt_version="v1",
            fixture_repos=[empty_sha_repo],
        )


def test_nonzero_temperature_raises() -> None:
    repo = FixtureRepo(full_name="org/repo", commit_sha="abc123", language="python")
    with pytest.raises(ConfigError, match="temperature"):
        EvalConfig(
            model="m",
            temperature=0.7,
            prompt_version="v1",
            fixture_repos=[repo],
        )


def test_empty_fixture_repos_raises() -> None:
    with pytest.raises(ConfigError, match="fixture_repos"):
        EvalConfig(model="m", temperature=0.0, prompt_version="v1", fixture_repos=[])


def test_negative_pass_rate_floor_raises() -> None:
    repo = FixtureRepo(full_name="org/repo", commit_sha="abc123", language="python")
    with pytest.raises(ConfigError, match="pass_rate_floor"):
        EvalConfig(
            model="m",
            temperature=0.0,
            prompt_version="v1",
            fixture_repos=[repo],
            pass_rate_floor=-1,
        )


def test_from_file_json(tmp_path: Path) -> None:
    data = {
        "model": "m",
        "temperature": 0.0,
        "prompt_version": "v1",
        "pass_rate_floor": 5,
        "fixture_repos": [
            {"full_name": "org/repo", "commit_sha": "abc123", "language": "python"},
        ],
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(data), encoding="utf-8")

    config = EvalConfig.from_file(config_path)

    assert config.model == "m"
    assert config.pass_rate_floor == 5
    assert config.fixture_repos[0].full_name == "org/repo"


def test_from_file_toml(tmp_path: Path) -> None:
    toml_text = """
model = "m"
temperature = 0.0
prompt_version = "v1"
pass_rate_floor = 5

[[fixture_repos]]
full_name = "org/repo"
commit_sha = "abc123"
language = "python"
"""
    config_path = tmp_path / "config.toml"
    config_path.write_text(toml_text, encoding="utf-8")

    config = EvalConfig.from_file(config_path)

    assert config.model == "m"
    assert config.fixture_repos[0].commit_sha == "abc123"


def test_from_file_unsupported_extension_raises(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("model: m", encoding="utf-8")

    with pytest.raises(ConfigError, match="unsupported"):
        EvalConfig.from_file(config_path)


def test_repo_by_name_missing_raises() -> None:
    with pytest.raises(ConfigError, match="no pinned fixture repo"):
        DEFAULT_CONFIG.repo_by_name("nonexistent/repo")
